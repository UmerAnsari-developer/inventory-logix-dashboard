"""DataCo SMART SUPPLY CHAIN Dataset Service.

Loads the DataCo dataset from the extracted CSV and maps columns to
project fields for use in the Inventory Logistics Optimization Dashboard.

Dataset: DataCo SMART SUPPLY CHAIN (Kaggle)
Source: shashwatwork/dataco-smart-supply-chain-for-big-data-analysis
Rows: 180,519 transactions | Columns: 53
"""

import os
import logging
import random

import pandas as pd
from flask import current_app

from ..utils.helpers import calculate_eoq as _calculate_eoq

LOGGER = logging.getLogger(__name__)

# Column mapping: DataCo CSV header -> Project field name
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


def _map_value(val):
    """Map a value, handling NaN and float-to-int conversion."""
    if pd.isna(val):
        return ''
    if isinstance(val, float) and val == int(val):
        return int(val)
    return str(val)


def _map_row_to_product(row, mapping=PRODUCT_MAPPING):
    """Map a dataset row to a product dict."""
    product = {}
    for dc_col, project_field in mapping.items():
        if dc_col in row.index:
            val = row[dc_col]
            product[project_field] = _map_value(val)
    return product


def _synthetic_products(limit=None):
    """Deterministic product catalogue used when the DataCo CSV is absent.

    The dataset file is gitignored, so fresh deployments (e.g. Render from
    GitHub) have no CSV. This fallback yields a realistic catalogue in the
    same shape as :func:`get_products` so seeding works identically on any
    environment.
    """
    categories = [
        "Electronics", "Apparel", "Home & Kitchen", "Sports & Outdoors",
        "Beauty & Personal Care", "Toys & Games", "Automotive", "Grocery",
        "Books", "Office Products",
    ]
    names = [
        "Bluetooth Speaker", "Laptop Stand", "Desk Lamp", "Water Bottle",
        "Wireless Mouse", "Yoga Mat", "Coffee Maker", "Running Shoes",
        "Headphones", "Backpack", "Wrist Watch", "Air Purifier", "Tea Kettle",
        "Gaming Controller", "USB-C Hub", "Hoodie", "Sneakers", "Blender",
        "Webcam", "Keyboard", "Monitor Arm", "Plant Pot", "Lunch Box",
        "Tool Kit", "Car Charger", "Fitness Tracker", "Notebook", "Pillow",
        "Curtain", "Cutting Board", "Toaster", "Hand Mixer", "Skincare Set",
        "Sunglasses", "Power Bank", "Router",
    ]
    tags = [
        "Eco", "Smart", "Pro", "Max", "Ultra", "Prime", "Flex", "Nova",
        "Aero", "Velo", "Vertex", "Titan", "Pulse", "Drift", "Summit",
        "Orbit", "Lumen", "Nexus",
    ]
    rng = random.Random(2024)
    products = []
    seen = set()
    for i in range(118):
        name = f"{rng.choice(names)} {rng.choice(tags)}"
        while name in seen:
            name = f"{rng.choice(names)} {rng.choice(tags)}"
        seen.add(name)
        category = categories[i % len(categories)]
        price = round(rng.uniform(9.99, 499.99), 2)
        products.append({
            "product_name": name,
            "product_card_id": str(1000 + i),
            "product_category_id": str(i % len(categories) + 1),
            "category_name": category,
            "product_price": price,
            "product_description": f"{category} - {name}",
            "sales_per_customer": round(rng.uniform(150.0, 2000.0), 2),
        })
    if limit:
        products = products[:limit]
    return products


def get_products(limit=None):
    """Get product data from DataCo dataset.

    Returns product dicts with EOQ calculation included. When the dataset CSV
    is not present (fresh Render deployment) a deterministic synthetic
    catalogue is returned instead so the app always seeds demo data.

    Each product dict contains:
    - Standard product fields
    - eoq: Economic Order Quantity
    - eoq_demand: Annual demand estimate
    - eoq_order_cost: Ordering cost per order
    - eoq_holding_cost: Holding cost per unit per year
    """
    try:
        df = _load_dataset()
    except FileNotFoundError:
        LOGGER.warning("DataCo dataset not found; using synthetic product catalogue.")
        return _synthetic_products(limit)

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