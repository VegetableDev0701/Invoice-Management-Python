class Prompts:
    def __init__(self, text):
        self.supplier_prompt = f"""
            Return the vendor name, the entity sending the invoice, from the document text delimited by triple backticks, ```{text}```. 
            
            Return in JSON format with key `vendor_name`. 
            
            All keys should have double quotes around them and make sure that it is in clean JSON form.
        """
        self.contract_prompt = f"""
            Please seperate out the 

            1. The Vendor for this Contract.
            2. The date of this contract in the format of mm-dd-yyyy
            3. The description of work summarized to in about 10 words.
            4. The amount to be billed.

            from the text delimted with triple backticks.

            Return in JSON format, with keys as follows: 
                `vendor`
                `date`
                `workDescription`
                `contractAmt`

            ```{text}```
        """
        self.line_items = f"""
            Please parse out each line of the following line items from this string form of a JSON shown below in triple backticks.  
            
            Please return in a JSON of the form:

            "line_item_1" :  
                "description": "<enter_description_here>", "amount: "<enter_amount_here>", "bounding_box": "<enter_bounding_box_data_here>", "page": "<enter_page_number_here>"
            

            RULES:
            1. Only return the JSON response and nothing else, and it MUST be valid JSON format with double quotes surrounding all keys and values.
            2. There should be a description and amount associated with every line item. 
            3. If multiple descriptions appear in the JSON string, concatenate them into a single description then summarize in your own words in about 15 words.
            4. If a description appears without an amount, return the amount as null. 
            5. Use the topHeight value from each dictionary object as a guide to associate related items, with a large amount of tolerance.
            6. For each line item with a description and amount take the bounding box where the "type": null for the bounding box for that line_item using topHeight to associate the bounding box correctly.
            7. Begin the line item numbering from 1 and continue sequentially with the first line item having the lowest topHeight and each following line item having a larger topHeight than the previous one.

            IMPORTANT:
            Always respond in valid JSON format, this is the most important part!!!

            ```{text}```
        """
        self.line_items_short = f"""
            Please parse the JSON string found delimted with triple backticks below, and return a JSON in the following structure:

            line_item_1: description, amount, bounding_box, page number

            RULES:

            1. Use valid JSON with double quotes for keys and values.
            2. Every line item must have a description, amount, bounding_box, and page. If no amount or description is present, return it as null.
            3. If multiple descriptions are present, combine them into a summarized 15-word description.
            4. Use the topHeight to link related items with a large tolerance.
            5. If a line item with a description and amount has a bounding box with type as null, use that.
            6. Arrange line items in sequential order according to topHeight.

            Only valid JSON should be returned.

            ```{text}```
        """

        self._line_items_description = f"Please rewrite these construction invoice line item descriptions, found delimited by triple backticks, succinctly in as few words as possible. Do not add single or double quotes to the returned string. ```{text}```"
        self.line_items_description = f"""If the line item descriptions, found delimted with triple backticks, are more than roughly 15 words, please summarize them in about 10 - 15 words. If not, leave them as is. Do not add single or double quotes to the returned string. ```{text}```"""
