"""DataCo SMART SUPPLY CHAIN Dataset Service.

Loads the DataCo dataset from the extracted CSV and maps columns to
project fields for use in the Inventory Logistics Optimization Dashboard.

Dataset: DataCo SMART SUPPLY CHAIN (Kaggle)
Source: shashwatwork/dataco-smart-supply-chain-for-big-data-analysis
Rows: 180,519 transactions | Columns: 53
"""

import os
import math
import pandas as pd
from flask import current_app

# Column mapping: DataCo CSV header -> Project field name
SUPPLIER_MAPPING = {
    # Customer as supplier mapping
    'Customer Id': 'supplier_id',
    'Customer Fname': 'supplier_first_name',
    'Customer Lname': 'supplier_last_name',
    'Customer Email': 'supplier_email',
    'Customer Segment': 'supplier_segment',
    'Customer City': 'supplier_city',
    'Customer Country': 'supplier_country',
    'Customer State': 'supplier_state',
    'Customer Street': 'supplier_street',
    'Customer Zipcode': 'supplier_zip',

    # Product as product mapping
    'Product Name': 'product_name',
    'Product Price': 'unit_price',
    'Product Description': 'product_description',
    'Product Status': 'product_status',
    'Product Category Id': 'product_category_id',

    # Order as order/inventory mapping
    'Order Id': 'order_id',
    'order date (DateOrders)': 'order_date',
    'Type': 'transaction_type',
    'Benefit per order': 'benefit_per_order',
    'Sales per customer': 'sales_per_customer',
    'Order Item Quantity': 'quantity',
    'Order Item Product Price': 'unit_price',
    'Order Item Discount': 'discount',
    'Order Item Discount Rate': 'discount_rate',
    'Order Item Total': 'order_total',
    'Order Profit Per Order': 'profit_per_order',
    'Order Item Product Price': 'product_price',

    # Shipping/shipping
    'Days for shipping (real)': 'shipping_days_real',
    'Days for shipment (scheduled)': 'shipping_days_scheduled',
    'Shipping Mode': 'shipping_mode',
    'Delivery Status': 'delivery_status',
    'Late_delivery_risk': 'late_delivery_risk',

    # Order region/state
    'Order Region': 'order_region',
    'Order State': 'order_state',
    'Order Zipcode': 'order_zipcode',

    # Customer location
    'Customer City': 'customer_city',
    'Customer Country': 'customer_country',
    'Customer State': 'customer_state',
    'Customer Street': 'customer_street',
    'Customer Zipcode': 'customer_zipcode',

    # Market
    'Market': 'market',

    # Product category
    'Category Id': 'category_id',
    'Category Name': 'category_name',
}


PRODUCT_MAPPING = {
    'Product Card Id': 'product_card_id',
    'Product Name': 'product_name',
    'Product Price': 'product_price',
    'Product Status': 'product_status',
    'Product Category Id': 'product_category_id',
    'Category Name': 'category_name',
    'Product Description': 'product_description',
    'Product Image': 'product_image',

    # EOQ-related fields
    'Sales per customer': 'sales_per_customer',
    'Order Item Quantity': 'order_quantity',
    'EOQ Calculation': 'eoq',
    'EOQ Demand': 'eoq_demand',
    'EOQ Order Cost': 'eoq_order_cost',
    'EOQ Holding Cost': 'eoq_holding_cost',
}


def _get_dataset_path():
    """Get path to the DataCo CSV dataset.
    
    Uses the application root path to locate the dataset.
    The dataset is expected at: <project_root>/datasets/DataCoSupplyChainDataset.csv
    """
    # Calculate project root from app root path
    # app.root_path is like: D:\MCA\3rd Sem\Mini Project\Inventory Logistics Optimization Dashboard\app
    # We want: D:\MCA\3rd Sem\Mini Project\Inventory Logistics Optimization Dashboard
    root = current_app.root_path.rsplit('app', 1)[0]
    csv_path = os.path.join(root, 'datasets', 'DataCoSupplyChainDataset.csv')
    
    if os.path.exists(csv_path):
        return csv_path
    
    # Fallback paths
    possible_paths = [
        os.path.join(current_app.root_path, 'datasets', 'DataCoSupplyChainDataset.csv'),
        os.path.join(current_app.root_path, 'datasets', 'dataco_supply_chain.csv'),
        os.path.join(current_app.root_path, 'datasets', 'DataCo_supply_chain.csv'),
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    raise FileNotFoundError("DataCo dataset CSV not found")


def _load_dataset():
    """Load the DataCo dataset."""
    csv_path = _get_dataset_path()
    encoding = 'latin1'
    return pd.read_csv(csv_path, encoding=encoding)


def _calculate_eoq(demand, order_cost, holding_cost):
    """Calculate Economic Order Quantity: EOQ = sqrt(2DS/H)

    Args:
        demand: Annual demand rate
        order_cost: Cost per order (S)
        holding_cost: Holding cost per unit per year (H)

    Returns:
        Economic Order Quantity (rounded to integer)
    """
    if holding_cost == 0:
        return 0
    return int(math.sqrt(2 * demand * order_cost / holding_cost))


def _map_value(val):
    """Map a value, handling NaN and float-to-int conversion."""
    if pd.isna(val):
        return ''
    if isinstance(val, float) and val == int(val):
        return int(val)
    return str(val)


def _map_row_to_supplier(row, mapping=SUPPLIER_MAPPING):
    """Map a dataset row to a supplier dict."""
    supplier = {}
    for dc_col, project_field in mapping.items():
        if dc_col in row.index:
            val = row[dc_col]
            supplier[project_field] = _map_value(val)
    return supplier


def _map_row_to_product(row, mapping=PRODUCT_MAPPING):
    """Map a dataset row to a product dict."""
    product = {}
    for dc_col, project_field in mapping.items():
        if dc_col in row.index:
            val = row[dc_col]
            product[project_field] = _map_value(val)
    return product


def get_suppliers(limit=None):
    """Get supplier data from DataCo dataset.

    Returns:
        list[dict]: List of supplier dicts with fields:
            - supplier_id: Customer Id
            - supplier_name: Fname Lname
            - supplier_email: Customer Email
            - supplier_segment: Customer Segment
            - supplier_city: Customer City
            - supplier_country: Customer Country
            - etc.
    """
    df = _load_dataset()

    available_cols = [col for col in SUPPLIER_MAPPING.keys() if col in df.columns]
    df_available = df[available_cols] if available_cols else df

    suppliers = []
    for _, row in df_available.iterrows():
        supplier = _map_row_to_supplier(row, SUPPLIER_MAPPING)
        if supplier.get('supplier_id') or supplier.get('supplier_name'):
            suppliers.append(supplier)

    seen_ids = set()
    unique_suppliers = []
    for s in suppliers:
        sid = s.get('supplier_id', '')
        if sid and sid not in seen_ids:
            seen_ids.add(sid)
            unique_suppliers.append(s)
        elif not sid and s not in unique_suppliers:
            unique_suppliers.append(s)

    if limit:
        unique_suppliers = unique_suppliers[:limit]

    return unique_suppliers


def get_products(limit=None):
    """Get product data from DataCo dataset.

    Returns product dicts with EOQ calculation included.

    Each product dict contains:
    - Standard product fields
    - eoq: Economic Order Quantity
    - eoq_demand: Annual demand estimate
    - eoq_order_cost: Ordering cost per order
    - eoq_holding_cost: Holding cost per unit per year
    """
    df = _load_dataset()

    available_cols = [col for col in PRODUCT_MAPPING.keys() if col in df.columns]
    df_available = df[available_cols] if available_cols else df

    products = []
    for _, row in df_available.iterrows():
        product = _map_row_to_product(row, PRODUCT_MAPPING)

        # Calculate EOQ from the mapped fields.
        # Use sales per customer as annual demand estimate, falling back to
        # order quantity * 12 (monthly usage extrapolated to a year).
        demand = float(product.get('sales_per_customer', 0) or 0) or (
            float(product.get('order_quantity', 0) or 0) * 12
        )
        unit_price = float(product.get('product_price', 0) or 0)
        order_cost = 50.0  # Default ordering cost estimate
        # Use 20% of unit price as holding cost, minimum $2
        holding_cost = max(2.0, unit_price * 0.20) if unit_price > 0 else 2.0

        # EOQ = sqrt(2DS/H); D=demand, S=order cost, H=holding cost
        eoq = _calculate_eoq(demand, order_cost, holding_cost)

        # If EOQ is unreasonably low, fall back to the quantity-based estimate.
        if eoq < 1:
            eoq = int(float(product.get('order_quantity', 0) or 0) * 12)
        if eoq < 1:
            eoq = 1  # Minimum EOQ of 1 unit

        product['eoq'] = eoq
        product['eoq_demand'] = demand
        product['eoq_order_cost'] = order_cost
        product['eoq_holding_cost'] = holding_cost

        products.append(product)

    # Remove duplicates based on product name + ID
    seen = set()
    unique_products = []
    for p in products:
        key = (p.get('product_name', ''), p.get('product_card_id', ''))
        if key not in seen:
            seen.add(key)
            unique_products.append(p)

    if limit:
        unique_products = unique_products[:limit]

    return unique_products


def get_inventory():
    """Get inventory-level data from the dataset.

    Returns inventory-like information including quantity and pricing.
    """
    df = _load_dataset()

    inventory_cols = [
        'Order Item Quantity',
        'Order Item Product Price',
        'Order Item Total',
        'Order Item Discount',
        'Order Item Discount Rate',
        'Order Item Profit Ratio',
        'Sales',
        'Benefit per order',
    ]

    available_cols = [col for col in inventory_cols if col in df.columns]
    if not available_cols:
        return []

    df_available = df[available_cols]

    inventory = []
    for _, row in df_available.iterrows():
        item = {
            'quantity': float(row.get('Order Item Quantity', 0) or 0),
            'unit_price': float(row.get('Order Item Product Price', 0) or 0),
            'order_total': float(row.get('Order Item Total', 0) or 0),
            'discount': float(row.get('Order Item Discount', 0) or 0),
            'discount_rate': float(row.get('Order Item Discount Rate', 0) or 0),
            'profit_ratio': float(row.get('Order Item Profit Ratio', 0) or 0),
            'sales': float(row.get('Sales', 0) or 0),
            'benefit_per_order': float(row.get('Benefit per order', 0) or 0),
        }
        inventory.append(item)

    return inventory


def get_orders(limit=None):
    """Get order data from the dataset.

    Returns order-level information including status, dates, etc.
    """
    df = _load_dataset()

    order_cols = [
        'Order Id',
        'order date (DateOrders)',
        'Order Status',
        'Order Region',
        'Order State',
        'Order Zipcode',
        'Type',
        'Benefit per order',
        'Sales per customer',
    ]

    available_cols = [col for col in order_cols if col in df.columns]
    if not available_cols:
        return []

    df_available = df[available_cols]

    orders = []
    for _, row in df_available.iterrows():
        order = {
            'order_id': str(row.get('Order Id', '')),
            'order_date': str(row.get('order date (DateOrders)', '')),
            'order_status': str(row.get('Order Status', '')),
            'order_type': str(row.get('Type', '')),
            'benefit_per_order': float(row.get('Benefit per order', 0) or 0),
            'sales_per_customer': float(row.get('Sales per customer', 0) or 0),
            'order_region': str(row.get('Order Region', '')),
            'order_state': str(row.get('Order State', '')),
        }
        orders.append(order)

    seen_ids = set()
    unique_orders = []
    for o in orders:
        oid = o.get('order_id', '')
        if oid and oid not in seen_ids:
            seen_ids.add(oid)
            unique_orders.append(o)
        elif not oid and o not in unique_orders:
            unique_orders.append(o)

    if limit:
        unique_orders = unique_orders[:limit]

    return unique_orders