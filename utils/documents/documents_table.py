from datetime import datetime
from typing import Any, Dict, List, Optional, Union
import copy

import pandas as pd
import numpy as np
import pytz
from google.cloud.documentai_v1.types.document import Document
import proto
from sklearn.mixture import GaussianMixture

from utils.model_utils import get_completion_gpt4
from utils.database import db_utils
from global_vars.prompts import Prompts
from global_vars import globals_db as gv_db


def parse_documents_table_row(
    document: Document,
    doc_id: str,
    doc_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parse a single row of the documents' table from the
    protobuf output.

    Parameters
    ----------
    document: gcp Document
    blob: str
        The blob object pointing to the file on gcs. This can be used to get
        the uri using `blob.name` is currently the
        gs://<dataset>/<project>/<%m%Y>/<doc_type>/<doc_fname>
    doc_type: str
        The document type that is output from the splitter classifier processor

    Returns
    -------
    Dictionary form for a single row of the documents table.
    """
    # TODO the doc_id here refers to the current gcs_uri, this will change
    # and this needs to be updated to reflect that change
    # TODO add doc_type as a function parameter and include in pushing to the BQ
    # project_id = doc_id.split("/")[1]
    total_amount_entity = [
        entity for entity in document.entities if entity.type_ == "total_amount"
    ]
    total_tax_amount_entity = [
        entity for entity in document.entities if entity.type_ == "total_tax_amount"
    ]

    tmp_row_dict = gv_db.DOCUMENT_INFO_TABLE_DICT.copy()

    tmp_row_dict = {
        "doc_id": doc_id,
        # when the document first gets processed it will be unknown and
        # this will stay null until the user places it in the correct project
        "project_id": None,  # TODO update this to include the unique id for a project
        "gcs_uri": None,
        "number_of_pages": len(document.pages),
        "document_type": doc_type,
        "date_received": datetime.now(pytz.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "supplier_id": None,  # TODO create function to query the table for the supplier id
        "processed": False,
        "approved": False,
        "total_tax_amount": (
            return_entity_norm_value_if_exists(total_tax_amount_entity[0])
            if total_tax_amount_entity
            else None
        ),
        "total_amount": (
            return_entity_norm_value_if_exists(total_amount_entity[0])
            if total_amount_entity
            else None
        ),
        "full_document_text": document.text.replace("\n", " "),
        # "is_project_confirmed": False,
        "pages": get_pages_json_record(document),
    }

    return tmp_row_dict


def return_entity_norm_value_if_exists(entity: proto.Message) -> float:
    """
    Returns the normalized entity value if it exists.

    Parameters
    ----------
    entity: proto.Message
        A single entity type
    Returns
    -------
    float
    """

    norm_value_entity = db_utils.parse_norm_value(entity.normalized_value, unit=False)

    if norm_value_entity:
        return norm_value_entity
    else:
        return entity.mention_text.replace("$", "")


def get_pages_json_record(document: proto.Message) -> List[Dict[str, Any]]:
    """
    A single document can have multiple pages. This returns
    the information like page resolution, the bytes string of that
    page, etc. in a list of JSON type objects, one for each page.

    Parameters
    ----------
    document: proto.Message

    Returns
    -------
    A list of JSON objects, one for each page.
    """
    page_list = []
    for page_num, page in enumerate(document.pages):
        pages = {
            "number": int(page_num + 1),
            "width": page.dimension.width,
            "height": page.dimension.height,
            "resolution_unit": page.dimension.unit,
            "image_content": page.image.content.hex(),
            "image_transform": parse_transforms(page.transforms),
        }
        page_list.append(pages)
    return page_list


def parse_transforms(
    transform: proto.marshal.collections.repeated.RepeatedComposite,
) -> Dict[str, Union[int, str]]:
    """
    Parse the transform matrix into a json record date type.
    Parameters
    ----------
    transform:
        The transform data used to with opencv to transform an image back

    Returns
    -------
    Dictionary with the transform data
    """
    # Will catch and return transforms only when they exist
    if transform:
        return {
            "rows": int(transform[0].rows),
            "cols": int(transform[0].cols),
            "type": int(transform[0].type_),
            "data": transform[0].data.hex(),
        }
    else:
        return None


async def create_line_items_gpt(data_orig: list) -> dict:
    """
    Document AI returns the line items as a list of all individual pieces of each line item.
    There is an list element for description, unit, amount, etc. depending on what the model
    picked up. This function takes in that list, figures out which descriptions, amounts etc.
    are all on a single line item using Gaussian Mixture Model, summarizes the descriptions
    using GPT4, and returns a `line_items_gpt` object to be used on the front end.

    Params:
        data_orig: list
            The list of line items returned from DocAI
    Returns:
        Dict
    """
    # make a deep copy so the orig doesn't get affected
    data = copy.deepcopy(data_orig)

    # get the cluster numbers from the number of amounts show
    # this is not perfect but will get close to the correct result
    cluster_num = 0
    for item in data:
        if item["entity_type_minor"] == "amount":
            cluster_num += 1
    # When the model doesn't pick up any line items
    if cluster_num == 0:
        return
    data = copy.deepcopy(data_orig)
    cluster_y_values = {}
    for i, item in enumerate(data):
        y_vals = []
        for box in item["bounding_box"].values():
            y_vals.append(box[1])
        cluster_y_values[i] = np.unique(y_vals)

    # Each bounding box as two y values so just average them here to
    # choose the middle height of the box
    X = []
    for arr in list(cluster_y_values.values()):
        X.append(np.mean(arr))
    X = np.array(X).reshape(-1, 1)

    model = GaussianMixture(n_components=cluster_num)
    yhat = model.fit_predict(X)
    # The number of clusters is chosen by how many `line_item_amounts` are found in the data.
    # However, it can find more `amount` line_items than clustered data, i.e. the data falls into
    # fewer clusters than it finds for amounts...invoices are very noisy and this just happens.
    # For these cases we remap the cluster numbers to be monotonically increasing from 0.
    # Let's say labels are [0, 2, 3, 4] and you want them to be [0, 1, 2, 3]
    unique_labels = np.unique(yhat)
    mapping = {yhat: i for i, yhat in enumerate(unique_labels)}
    # Apply the mapping to your labels
    yhat = np.array([mapping[yhat] for yhat in yhat])
    for i, item in enumerate(data):
        item["cluster"] = yhat[i]

    df_list = []
    for item in data:
        bounding_box = item["bounding_box"]
        del item["bounding_box"]
        tmp_df = pd.DataFrame(item, index=[0])
        (
            tmp_df["ul_x"],
            tmp_df["ul_y"],
            tmp_df["ll_x"],
            tmp_df["ll_y"],
            tmp_df["lr_x"],
            tmp_df["lr_y"],
            tmp_df["ur_x"],
            tmp_df["ur_y"],
        ) = (
            bounding_box["ul"][0],
            bounding_box["ul"][1],
            bounding_box["ll"][0],
            bounding_box["ll"][1],
            bounding_box["lr"][0],
            bounding_box["lr"][1],
            bounding_box["ur"][0],
            bounding_box["ur"][1],
        )
        df_list.append(tmp_df)

    data_df = pd.concat(df_list).reset_index()

    # create the line_items_gpt
    data_gb_df = (
        data_df.groupby("cluster")[["ul_y", "lr_y", "lr_x", "ul_x"]]
        .agg({"ul_y": min, "lr_y": max, "lr_x": max, "ul_x": min})
        .reset_index()
        .rename(
            columns={
                "ul_y": "y_top",
                "lr_y": "y_bottom",
                "ul_x": "x_left",
                "lr_x": "x_right",
            }
        )
    )
    # For line_items we want the most right and left x-axis points to encompass
    # the entire line item each time. Add a .5% buffer to each side.
    x_right = data_gb_df["x_right"].max() + 0.005
    x_left = data_gb_df["x_left"].min() - 0.005

    data_df_merged = data_df.merge(data_gb_df, how="left", on="cluster")
    # create the dictionary and use GPT4 to rewrite the descriptions
    line_item = {}
    for group, df in data_df_merged.groupby("cluster"):
        description = (
            df.query("entity_type_minor == 'description'")
            .groupby("entity_type_minor")["entity_value_raw"]
            .agg(" ".join)
        )
        try:
            description = description.values[0]
            message = Prompts(description).line_items_description
            description = await get_completion_gpt4(
                messages=message,
                max_tokens=50,
                temperature=0.3,
                job_type="line_item_description",
            )
        except IndexError:
            description = None
        ul_y = df["y_top"].min()
        lr_y = df["y_bottom"].max()
        expand_height_by = (lr_y - ul_y) / 4
        ul_y = ul_y - expand_height_by
        lr_y = lr_y + expand_height_by
        try:
            page = df["page_reference"].unique()
        except KeyError:
            page = None
        try:
            amount = df.query("entity_type_minor == 'amount'")[
                "entity_value_raw"
            ].values[0]
        except (KeyError, IndexError):
            amount = None
        line_item[group] = {
            "description": description,
            "bounding_box": {
                "ul": [x_left, ul_y],
                "ur": [x_right, None],
                "lr": [x_right, lr_y],
                "page": int(page[0]),
            },
            "amount": amount,
        }
    # sort the line items in order from the top of the first page down
    tmp_df_list = []
    for key, val in line_item.items():
        tmp_df_list.append(
            pd.DataFrame(
                {
                    "top_height": val["bounding_box"]["ul"][1],
                    "page": val["bounding_box"]["page"],
                    "cluster": key,
                },
                index=[key],
            )
        )
    tmp_df = pd.concat(tmp_df_list).sort_values(
        by=["page", "top_height"],
    )
    tmp_df["line_items"] = [f"line_item_{i+1}" for i in range(len(tmp_df))]

    tmp_df = pd.DataFrame(tmp_df).merge(
        pd.DataFrame(line_item.values()), right_index=True, left_on=["cluster"]
    )

    line_items_gpt = (
        tmp_df.set_index("line_items")
        .drop(columns=["cluster", "top_height"])
        .to_dict("index")
    )

    return line_items_gpt
