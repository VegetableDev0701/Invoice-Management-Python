from typing import Any


def find_index(lst, key, value):
    for i, dic in enumerate(lst):
        if dic[key] == value:
            return i
    return -1


def parse_norm_value(norm_value: object, unit: bool) -> Any:
    """
    The protobuf output contains normalized values, i.e. $1400.00 -> 1400.0.
    This grabs those values and adds them to the table.

    Parameters
    ----------
    norm_value: protobuf object
    unit: bool
        If a unit is included like with currency, this will return that unit.

    Returns
    -------
    The normalized value for that entity. Could be of any type.
    """

    if "money_value" in norm_value:
        if unit:
            return norm_value.money_value.currency_code
        else:
            return float(
                norm_value.money_value.units
                + int(str(norm_value.money_value.nanos).zfill(9)[:2]) / 100
            )
    elif "date_value" in norm_value:
        if unit:
            return
        else:
            return norm_value.text
    else:
        if unit:
            return
        else:
            # This is a placeholder for if there are other
            # normalized values that we can insert them here.
            # For now it will catch any other normalized value and
            # return the raw text.
            return norm_value.text


def format_filename(filename: str) -> str:
    """
    Removes any whitespace in the filename of the pdf and
    replaces with an underscore.
    """
    return filename.replace(" ", "_")


def set_target_value(target_id, input_elements, set_value):
    """
    Finds a value by its id in the nested form data and sets a new value.
    """
    for element in input_elements:
        if is_input_element_with_items(element):
            found_item = next(
                (item for item in element["items"] if item["id"] == target_id), None
            )
            if found_item:
                found_item["value"] = set_value
                return
        if is_input_element_with_address_elements(element):
            for address_element in element["addressElements"]:
                found_item = next(
                    (
                        item
                        for item in address_element["items"]
                        if item["id"] == target_id
                    ),
                    None,
                )
                if found_item:
                    found_item["value"] = set_value
                    return


# Two helper functions for the above update_target_value function.
def is_input_element_with_address_elements(element):
    return "addressElements" in element and element["addressElements"] is not None


def is_input_element_with_items(element):
    return "items" in element and element["items"] is not None
