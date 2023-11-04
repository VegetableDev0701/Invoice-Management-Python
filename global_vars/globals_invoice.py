INVOICE_FIELDS = [
    "due_date",
    "ship_to_name",
    "currency",
    "total_amount",
    "amount_paid_since_last_invoice",
    "carrier",
    "currency_exchange_rate",
    "receiver_tax_id",
    "delivery_date",
    "freight_amount",
    "invoice_date",
    "invoice_id",
    "line_item/amount",
    "line_item/description",
    "line_item/product_code",
    "line_item/purchase_order",
    "line_item/quantity",
    "line_item/unit",
    "line_item/unit_price",
    "net_amount",
    "payment_terms",
    "purchase_order",
    "receiver_address",
    "receiver_email",
    "receiver_name",
    "receiver_phone",
    "receiver_website",
    "remit_to_address",
    "remit_to_name",
    "ship_from_address",
    "ship_from_name",
    "ship_to_address",
    "supplier_address",
    "supplier_email",
    "supplier_iban",
    "supplier_name",
    "supplier_payment_ref",
    "supplier_registration",
    "supplier_tax_id",
    "supplier_website",
    "total_tax_amount",
    "vat/amount",
    "vat/category_code",
    "vat/tax_amount",
    "vat/tax_rate",
    "supplier_phone",
]

PROJECT_ENTITIES_FOR_MATCHING = [
    # "ship_from_address",
    # "ship_to_name",
    # "receiver_address",
    # "receiver_email",
    "receiver_name",
    # "receiver_phone",
    # "receiver_website",
    # "ship_from_address",
    # "ship_from_name",
    "ship_to_address",
]

RECEIPT_FIELDS = [
    "currency",
    "end_date",
    "net_amount",
    "purchase_time",
    "receipt_date",
    "start_date",
    "supplier_address",
    "supplier_city",
    "supplier_name",
    "tip_amount",
    "total_amount",
    "total_tax_amount",
    "line_item",
    "line_item/amount",
    "line_item/description",
    "line_item/product_code",
]

TAX_FIELDS = [
    "total_tax_amount",
    "vat/amount",
    "vat/category_code",
    "vat/tax_amount",
    "vat/tax_rate",
]

SUPPLIER_FIELDS = [
    "remit_to_name",
    "supplier_address",
    "supplier_email",
    "supplier_iban",
    "supplier_name",
    "supplier_payment_ref",
    "supplier_registration",
    "supplier_tax_id",
    "supplier_website",
    "supplier_phone",
]

SUPPLIER_FIELDS_FOR_TEXT_GENERATION = [
    "supplier_name",
    "supplier_address",
    "supplier_phone",
    "supplier_email",
    "supplier_website",
    "remit_to_name",
]

SUPPLIER_NAME_FIELDS = ["supplier_name", "remit_to_name"]

TOTAL_AMOUNT_FIELDS = ["net_amount", "total_amount"]

FINAL_INVOICE_KEYS = [
    "invoice_number",
    "invoice_date",
    "date_received",
    "supplier_name",
    "total_amount",
    "total_tax",
    "currency",
]

FINAL_KEY_MAP = {
    "supplier_name": SUPPLIER_FIELDS,
    "total_amount": TOTAL_AMOUNT_FIELDS,
    "total_tax": TAX_FIELDS,
    "currency": ["currency"],
    "invoice_number": ["invoice_id"],
    "invoice_date": ["invoice_date"],
    "date_received": ["date_received"],
}

PROJECT_DETAILS_MATCHING_KEYS = [
    "project-supervisor",
    "project-address",
    "client-first-name",
    "client-last-name",
]
