import asyncio
import json
import re
from typing import List, Tuple
from dotenv import load_dotenv
import os
import logging
import sys

import numpy as np
import openai
from thefuzz import process, fuzz
from sentence_transformers import SentenceTransformer, util
from torch import Tensor

from config import Config, PROJECT_NAME
from utils import model_utils
from utils.database.firestore import fetch_all_vendor_summaries
from global_vars.globals_invoice import PROJECT_ENTITIES_FOR_MATCHING
from global_vars.prompts import Prompts
from utils.data_models.vendors import PredictedVendorModel

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# Create a logger
logger = logging.getLogger("error_logger")
logger.setLevel(logging.DEBUG)

try:
    # Create a file handler
    handler = logging.FileHandler(
        "/Users/mgrant/STAK/app/stak-backend/api/logs/matching_algorithm_logger.log"
    )
except:
    # Create stremhandler for docker
    handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(handler)


async def make_project_prediction(
    doc_dict: dict,
    project_docs: dict,
    match_customer_patterns_list: list[str],
    address_choices: list[str],
    owner_choices: list[str],
    model: SentenceTransformer,
    doc_emb: np.ndarray,
) -> Tuple[str, float, dict]:
    """
    Make a project prediction based on a document and a query.

    This function predicts the most likely project based on a document and a query, using
    fuzzy matching and cosine similarity between the document embedding and the query
    embedding.

    Args:
        doc_dict (dict): A dictionary containing information about the document.
        project_docs (str): Dictionary with project metadata.
        match_customer_patterns_list (list[str]): A list of customer patterns to match against.
        address_choices (list[str]): A list of address choices to match against.
        owner_choices (list[str]): A list of owner choices to match against.
        model (sentence_transformers.SentenceTransformer.SentenceTransformer): A SentenceTransformer
            model used to encode the query and document.
        doc_emb (np.ndarray): The document embedding.

    Returns:
        A tuple containing the project prediction (a string), the maximum cosine similarity
        score (a float), and a dictionary of the top 5 address choices with their cosine
        similarity scores (a dict).
    """

    # Get the best match from the document using fuzzy matching
    query_to_embed, address = await get_matches_from_document(
        doc_dict,
        customer_pattern_list=match_customer_patterns_list,
        use_fuzzy_matching=True,
        address_choices=address_choices,
        owner_choices=owner_choices,
    )

    # Encode the query and calculate cosine similarity with the document embedding
    query_emb = model.encode(query_to_embed, convert_to_tensor=False)
    scores = util.cos_sim(query_emb, doc_emb)[0].cpu().tolist()

    # Sort address choices by cosine similarity and return top 5
    doc_score_pairs = sorted(
        list(zip([address for address in address_choices], scores)),
        key=lambda x: x[1],
        reverse=True,
    )
    top_scores_dict = {
        "top_scores": dict(doc_score_pairs[: Config.N_TOP_SCORES_TO_KEEP])
    }

    max_val = max(scores)
    max_index = scores.index(max_val)

    # If the address matches exactly and there is high confidence, predict the address as the project
    if (
        address.lower()
        in [x.lower() for x in address_choices]
        # and max_val >= Config.PREDICTION_CONFIDENCE_CUTOFF_WITH_ADDRESS_MATCH
    ):
        prediction = address
    # If the maximum cosine similarity score is below a threshold, predict 'unknown'
    elif max_val < Config.PREDICTION_CONFIDENCE_CUTOFF:
        prediction = "unknown"
    # Otherwise, predict the address with the highest cosine similarity score
    else:
        prediction = address_choices[max_index]

    if prediction != "unknown":
        pred_index = address_choices.index(prediction)
        project = project_docs[[*project_docs.keys()][pred_index]]
        project_name = project["project_name"]
        uuid = project["uuid"]
        address_id = project["address_id"]
        pred_score = scores[pred_index]

        return {
            "name": project_name,
            "address": prediction,
            "score": pred_score,
            "top_scores": top_scores_dict["top_scores"],
            "uuid": uuid,
        }
    else:
        ## TODO Implement the LLM Api here
        ## Need accesss to GPT-4 to make this work. GPT3.5 is not good enough.
        return {
            "name": None,
            "value": None,
            "score": None,
            "top_scores": top_scores_dict["top_scores"],
            "uuid": None,
        }


def get_data_for_predictions(
    project_docs,
) -> Tuple[list[str], list[str], SentenceTransformer, np.ndarray]:
    """
    Quick wrapper to grab all necessary data to make a project prediction.

    Args:
        project_docs: dict
            Dictionary of the metadata needed to make a prediction.
    Returns:
        tuple
    """
    address_choices = get_address_choices_list(project_docs)
    owner_choices = get_owner_choices_list(project_docs)
    docs = get_project_docs_for_embeddings(project_docs)
    model, doc_emb = init_sentence_similarity_model(docs)

    return address_choices, owner_choices, model, doc_emb


def get_project_docs_for_embeddings(project_docs: dict) -> list[str]:
    """
    Loop through projects dictionary and return a list of the strings that
    will be used to make the text embeddings used for classification.
    """
    docs = [project["doc"] for project in project_docs.values()]
    return docs


def get_address_choices_list(project_docs: dict) -> list[str]:
    """Generates a list of unique project addresses for fuzzy matching.

    This function takes a dictionary of project documents, and extracts the 'address'
    field from each project, excluding the 'unknown' project. The list of addresses
    is then deduplicated to create a list of unique address choices.

    Args:
        project_docs (dict): A dictionary containing project documents.
            Each document is assumed to have an 'address' field.

    Returns:
        list[str]: A list of unique addresses.
    """
    address_list = [
        project_docs[project]["address"]
        for project in project_docs
        if project != "unknown"
    ]
    return address_list


def get_owner_choices_list(project_docs: dict) -> list[str]:
    """Generates a list of unique project owners for fuzzy matching.

    This function takes a dictionary of project documents, and extracts the 'owner'
    field from each project, excluding the 'unknown' project. The list of owners
    is then deduplicated to create a list of unique owner choices.

    Args:
        project_docs (dict): A dictionary containing project documents.
            Each document is assumed to have an 'owner' field.

    Returns:
        list[str]: A list of unique owner names.
    """
    owner_list = list(
        set(
            [
                project_docs[project]["owner"]
                for project in project_docs
                if project != "unknown"
            ]
        )
    )
    return owner_list


def init_sentence_similarity_model(docs: list[str]):
    """
    Load the pretrained model to run sentence similarity on the
    supplier information from the `raw_entities` table and the `suppliers` table.

    Parameters
    ----------
    docs: List[str]
        List of the supplier information from the `suppliers` table.

    Returns
    -------
    Tuple[loaded NLP model, array of the embeddings for the supplier information strings]
    """
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    doc_emb = model.encode(docs)

    return model, doc_emb


async def get_matched_patterns_regex(
    string_to_match: str, match_patterns: list[str], is_address: bool
) -> str:
    """
    This finds patterns and matches the string after those matches.

    Args:
        string_to_match: str
            The raw invoice text.
        match_patterns: list[str]
            A list of patterns to match
        is_adddress: bool
            Whether we are trying to match an address or not.

    Returns:
        A string of all the matches.

    Example:
        Customer Ref: Michael Grant
        This would look for customer ref and then grab 40 characters after
        to pickup `Michael Grant`
    """
    string_matches = []
    for match in match_patterns:
        match = await asyncio.to_thread(
            re.search, match, string_to_match, re.IGNORECASE
        )
        if match:
            start = match.start()
            end = match.end()
            if is_address:
                string_extracted = string_to_match[start:end].replace("\n", " ").strip()
            else:
                string_extracted = re.sub(
                    r"[^\w\s]",
                    "",
                    string_to_match[
                        end : end + Config.CUSTOMER_REGEX_POST_CHARACTERS
                    ].replace("\n", " "),
                ).strip()
            string_matches.append(string_extracted)
    return " ".join(string_matches)


async def get_matches_from_document(
    doc_dict: dict,
    customer_pattern_list: list[str],
    address_pattern_list: list[str] | None = None,
    use_fuzzy_matching: bool | None = None,
    address_choices: list[str] | None = None,
    owner_choices: list[str] | None = None,
) -> Tuple[str, str]:
    """Generates a query string to match the document to a project.

    The function uses regular expressions and/or fuzzy matching to match patterns
    in the document's full text with customer patterns, address patterns, and owner choices.
    The matches are then combined to create a query string.

    Args:
        doc_dict (dict): The document dictionary containing the document's full text and entities.
        customer_pattern_list (list[str]): The list of customer patterns to match.
        address_pattern_list (list[str], optional): The list of address patterns to match. Defaults to None.
        use_fuzzy_matching (bool, optional): Whether to use fuzzy matching or not. Defaults to None.
        address_choices (list[str], optional): The list of address choices for fuzzy matching. Defaults to None.
        owner_choices (list[str], optional): The list of owner choices for fuzzy matching. Defaults to None.

    Returns:
        str: The combined query string derived from the matched patterns.
    """
    tmp_list = []
    full_text = doc_dict["full_document_text"].replace("\n", " ")
    customer_matches = await get_matched_patterns_regex(
        full_text, match_patterns=customer_pattern_list, is_address=False
    )
    if use_fuzzy_matching:
        if address_choices:
            address_matches = await asyncio.to_thread(
                process.extractOne,
                full_text,
                address_choices,
                scorer=fuzz.token_set_ratio,
                score_cutoff=Config.THEFUZZ_SCORE_CUTOFF,
            )
            if address_matches:
                address_matches = address_matches[0]
            else:
                address_matches = ""
        else:
            address_matches = ""
        if owner_choices:
            owner_matches = await asyncio.to_thread(
                process.extractOne,
                full_text,
                owner_choices,
                scorer=fuzz.token_set_ratio,
            )
            if owner_matches:
                owner_matches = owner_matches[0]
            else:
                owner_matches = ""
        else:
            owner_choices = ""

    else:
        address_matches = await get_matched_patterns_regex(
            full_text, match_patterns=address_pattern_list, is_address=True
        )
        if owner_choices:
            owner_matches = await get_matched_patterns_regex(
                full_text, match_patterns=owner_choices, is_address=True
            )

    if address_choices and owner_choices and customer_matches:
        all_matches = f"{customer_matches.strip()} {address_matches.strip()} {owner_matches.strip()}"
    elif address_choices and owner_choices:
        all_matches = f"{address_matches} {owner_matches}"
    elif address_choices:
        all_matches = f"{customer_matches} {address_matches}"
    elif owner_choices:
        all_matches = f"{customer_matches} {owner_matches}"
    else:
        all_matches = f"{customer_matches}"

    for ent in doc_dict["entities"]:
        if ent["entity_type_major"] in PROJECT_ENTITIES_FOR_MATCHING:
            tmp_list.append(ent["entity_value_raw"].replace("\n", " "))
    tmp_list.append(all_matches.strip())
    return " ".join(tmp_list), address_matches


# TODO When we get all the vendors from a customer update this to scan the known
# `vendor addresses` and `phone number`, and `website` to see if a match can be made.


async def get_vendor_name(
    doc_dict: dict,
    full_text: str,
    score_cutoff: float = Config.VENDOR_NAME_CONFIDENCE_CUTOFF,
) -> dict:
    """
    Gets the supplier's name based on the provided documents and criteria.

    This function uses a given document dictionary to identify a supplier's name.
    If the confidence score of the identified entity is higher than the provided
    cutoff, the normalized value is considered the supplier's name. If the score
    is lower, the name is logged as an error. The function also handles
    'remit_to_name' entities in a similar manner.

    In case no supplier name is found or if an error occurs during the process,
    it attempts to get a completion from an external API.

    Args:
        doc_dict (dict): The document dictionary containing entities from which
            the supplier's name is to be identified.
        full_text (str): The full text used for generating prompts.
        score_cutoff (float, optional): The confidence score cutoff for identifying
            supplier names. Defaults to Config.VENDOR_NAME_CONFIDENCE_CUTOFF.

    Returns:
        str: The identified supplier's name, or None if not found or an error occurs.
    """
    prompt = Prompts(full_text)
    error_log = {}
    for ent in doc_dict["entities"]:
        if ent["entity_type_major"] == "supplier_name":
            if float(ent["confidence_score"]) > score_cutoff:
                if ent["entity_value_norm"] is not None:
                    ent.update(
                        {
                            "supplier_name": ent["entity_value_norm"],
                            "score": ent["confidence_score"],
                            "isGPT": False,
                        }
                    )
                    return ent
                else:
                    ent.update(
                        {
                            "supplier_name": ent["entity_value_raw"],
                            "score": ent["confidence_score"],
                            "isGPT": False,
                        }
                    )
                    return ent
            else:
                if ent["entity_value_norm"] is not None:
                    error_log.update(
                        {
                            "supplier_name": ent["entity_value_norm"],
                            "score": ent["confidence_score"],
                            "isGPT": False,
                        }
                    )
                else:
                    error_log.update(
                        {
                            "supplier_name": ent["entity_value_raw"],
                            "score": ent["confidence_score"],
                            "isGPT": False,
                        }
                    )
        elif ent["entity_type_major"] == "remit_to_name":
            if float(ent["confidence_score"]) > score_cutoff:
                if ent["entity_value_norm"] is not None:
                    ent.update(
                        {
                            "supplier_name": ent["entity_value_norm"],
                            "score": ent["confidence_score"],
                            "isGPT": False,
                        }
                    )
                    return ent
                else:
                    ent.update(
                        {
                            "supplier_name": ent["entity_value_raw"],
                            "score": ent["confidence_score"],
                            "isGPT": False,
                        }
                    )
                    return ent
            else:
                if ent["entity_value_norm"] is not None:
                    error_log.update(
                        {
                            "supplier_name": ent["entity_value_norm"],
                            "score": ent["confidence_score"],
                            "isGPT": False,
                        }
                    )
                else:
                    error_log.update(
                        {
                            "supplier_name": ent["entity_value_raw"],
                            "score": ent["confidence_score"],
                            "isGPT": False,
                        }
                    )

        else:
            continue
    try:
        response: str | None = await model_utils.get_completion_gpt4(
            prompt.supplier_prompt, max_tokens=100, job_type="vendor_matching"
        )
        if response:
            if not isinstance(response, str):
                return {"supplier_name": None, "isGPT": True}
            else:
                response = response.replace("\n", "").replace("```", "")
            try:
                return {
                    "supplier_name": json.loads(response)["vendor_name"],
                    "isGPT": True,
                }
            except json.JSONDecodeError:
                logger.exception(
                    f"GPT API returned a value that was not a valid JSON: {response} "
                )
                return {"supplier_name": None, "isGPT": True}
        else:
            return {"supplier_name": None, "isGPT": True}
    except (
        openai.error.APIConnectionError,
        openai.error.RateLimitError,
        Exception,
    ) as e:
        logger.exception(
            f"An error occured while extracting vendor_name from document: {e}"
        )
        return {"supplier_name": error_log["supplier_name"], "isGPT": False}


async def match_predicted_vendor(
    company_id: str,
    pred_vendor_name_dict: dict | None,
    all_vendor_summary_list: dict | None = None,
    model: SentenceTransformer | None = None,
    vendors_emb: List[Tensor] | np.ndarray | Tensor | None = None,
) -> PredictedVendorModel:
    """
    Match the predicted vendor name to the list of vendors from the quickbooks-desktop
    data in Firestore. This is the master list of Vendor's from QBD that includes
    the Agave UUID needed to send data back to QBD.

    params:
        vendor_name(str): the predicted vendor name from the processing step
    returns:
        matched_vendor_name(dict): the vendor name and uuid
    """
    if all_vendor_summary_list is None:
        all_vendor_summary_list = await fetch_all_vendor_summaries(
            company_id=company_id, project_name=PROJECT_NAME
        )

    # Using dict.get() with a default value of an empty dict for "vendor"
    vendor_name = pred_vendor_name_dict.get(
        "supplier_name"
    ) or pred_vendor_name_dict.get("vendor", {}).get("name")
    is_invoice = "supplier_name" in pred_vendor_name_dict

    if all_vendor_summary_list:
        vendor_name_list = [
            {
                "name": vendor.get("vendorName"),
                "agave_uuid": vendor.get("agave_uuid"),
                "uuid": vendor.get("uuid"),
            }
            for vendor in all_vendor_summary_list
            if vendor
        ]
        if vendor_name_list:
            # init model with all vendor names
            # check if this is an invoice or contract
            if vendor_name is None:
                if is_invoice:
                    pred_vendor_name_dict.update(
                        {
                            "agave_uuid": None,
                            "vendor_match_conf_score": None,
                        }
                    )
                    return pred_vendor_name_dict
                else:
                    pred_vendor_name_dict.update(
                        {
                            "vendor": {
                                "name": vendor_name,
                                "agave_uuid": None,
                                "vendor_match_conf_score": None,
                            },
                        }
                    )
                    return pred_vendor_name_dict
            # only initialize the model if model and vendors_emb was not added as a a param
            # and if vendor_name is not None.
            if model is None and vendors_emb is None:
                model, vendors_emb = init_sentence_similarity_model(
                    [x["name"] for x in vendor_name_list]
                )
        else:
            if is_invoice:
                pred_vendor_name_dict.update(
                    {
                        "agave_uuid": None,
                        "vendor_match_conf_score": None,
                    }
                )
                return pred_vendor_name_dict
            else:
                pred_vendor_name_dict.update(
                    {
                        "vendor": {
                            "name": vendor_name,
                            "agave_uuid": None,
                            "vendor_match_conf_score": None,
                        },
                    }
                )
                return pred_vendor_name_dict

        # create the query embedding from the predicted vendor name
        vendor_name_emb = model.encode(vendor_name, convert_to_tensor=False)

        scores = util.cos_sim(vendor_name_emb, vendors_emb)[0].cpu().tolist()

        max_value = max(scores)
        max_index = scores.index(max_value)

        if max_value > Config.PREDICTION_CONFIDENCE_CUTOFF:  # currently set 0.6
            if is_invoice:
                return {
                    "supplier_name": vendor_name_list[max_index]["name"],
                    "agave_uuid": vendor_name_list[max_index]["agave_uuid"],
                    "uuid": vendor_name_list[max_index]["uuid"],
                    "vendor_match_conf_score": scores[max_index],
                    "isGPT": pred_vendor_name_dict.get("isGPT"),
                    "score": pred_vendor_name_dict.get("score"),
                }
            else:
                pred_vendor_name_dict.update(
                    {
                        "vendor": {
                            "name": vendor_name_list[max_index]["name"],
                            "uuid": vendor_name_list[max_index]["uuid"],
                            "agave_uuid": vendor_name_list[max_index]["agave_uuid"],
                            "vendor_match_conf_score": scores[max_index],
                        },
                    }
                )
        else:
            if is_invoice:
                pred_vendor_name_dict.update(
                    {
                        "agave_uuid": None,
                        "vendor_match_conf_score": None,
                    }
                )
            else:
                pred_vendor_name_dict.update(
                    {
                        "vendor": {
                            "name": vendor_name,
                            "agave_uuid": None,
                            "vendor_match_conf_score": None,
                        },
                    }
                )

    else:
        if is_invoice:
            pred_vendor_name_dict.update(
                {
                    "agave_uuid": None,
                    "vendor_match_conf_score": None,
                }
            )
        else:
            pred_vendor_name_dict.update(
                {
                    "vendor": {
                        "name": vendor_name,
                        "uuid": None,
                        "agave_uuid": None,
                        "vendor_match_conf_score": None,
                    },
                }
            )


    return pred_vendor_name_dict
