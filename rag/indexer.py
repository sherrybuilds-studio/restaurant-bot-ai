import json
import os
import shutil
import chromadb
from chromadb.utils import embedding_functions

MENU_PATH = os.path.join(os.path.dirname(__file__), "../data/menu.json")
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "../chroma_db")


def load_menu():
    with open(MENU_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_documents(menu_data):
    docs = []
    ids = []
    metadatas = []

    restaurant = menu_data["restaurant"]

    # Restaurant info block
    info_text = (
        f"Restaurant: {restaurant['name']}. {restaurant['tagline']}. "
        f"Cuisine: {restaurant['cuisine']}. "
        f"Address: {restaurant['address']['street']}, {restaurant['address']['district']}, {restaurant['address']['city']} {restaurant['address']['postal_code']}. "
        f"Phone: {restaurant['contact']['phone']}. "
        f"Email: {restaurant['contact']['email']}. "
        f"Website: {restaurant['contact']['website']}. "
        f"Instagram: {restaurant['contact']['instagram']}."
    )
    docs.append(info_text)
    ids.append("info_restaurant")
    metadatas.append({"type": "restaurant_info", "category": "info"})

    # Opening hours
    hours = restaurant["opening_hours"]
    hours_text = (
        f"Opening hours for {restaurant['name']}: "
        f"Monday {hours['monday']}, Tuesday {hours['tuesday']}, Wednesday {hours['wednesday']}, "
        f"Thursday {hours['thursday']}, Friday {hours['friday']}, Saturday {hours['saturday']}, Sunday {hours['sunday']}. "
        f"Kitchen closes {hours['kitchen_closes']}. Note: {hours['note']}."
    )
    docs.append(hours_text)
    ids.append("info_hours")
    metadatas.append({"type": "opening_hours", "category": "info"})

    # Reservation policy
    rp = restaurant["reservation_policy"]
    policy_text = (
        f"Reservation policy at {restaurant['name']}: "
        f"Required for {rp['required_for']}. Walk-ins {rp['walk_ins']}. "
        f"Book up to {rp['max_advance_booking_days']} days in advance. "
        f"Cancellation: {rp['cancellation_policy']}. "
        f"Groups of 6+: {rp['large_group_policy']}. "
        f"No-show policy: {rp['no_show_policy']}. "
        f"Table hold time: {rp['table_hold_time']}."
    )
    docs.append(policy_text)
    ids.append("info_reservation_policy")
    metadatas.append({"type": "reservation_policy", "category": "info"})

    # Special features
    features_text = (
        f"Special features at {restaurant['name']}: "
        + " | ".join(restaurant["special_features"])
    )
    docs.append(features_text)
    ids.append("info_features")
    metadatas.append({"type": "features", "category": "info"})

    # Payment
    payment = restaurant["payment"]
    payment_text = (
        f"Payment at {restaurant['name']}: Accepted methods: {', '.join(payment['accepted'])}. "
        f"Service charge: {payment['service_charge']}. Currency: {payment['currency']}."
    )
    docs.append(payment_text)
    ids.append("info_payment")
    metadatas.append({"type": "payment", "category": "info"})

    # Parking / transport
    docs.append(f"Parking and transport for {restaurant['name']}: {restaurant['parking']}")
    ids.append("info_parking")
    metadatas.append({"type": "parking", "category": "info"})

    # FAQ entries
    for i, faq in enumerate(menu_data.get("faq", [])):
        faq_text = f"FAQ — Q: {faq['question']} A: {faq['answer']}"
        docs.append(faq_text)
        ids.append(f"faq_{i:02d}")
        metadatas.append({"type": "faq", "category": "info"})

    # Menu items
    all_items = []
    for category in ["starters", "mains", "desserts", "drinks"]:
        all_items.extend(menu_data["menu"].get(category, []))

    for item in all_items:
        allergen_str = ", ".join(item.get("allergens", [])) if item.get("allergens") else "none"
        flags = []
        if item.get("vegan"):
            flags.append("vegan")
        if item.get("vegetarian") and not item.get("vegan"):
            flags.append("vegetarian")
        if item.get("halal"):
            flags.append("halal")
        if item.get("chef_special"):
            flags.append("chef's special")

        price = item.get("price", 0)
        price_str = f"€{price:.2f}"
        if "price_glass" in item:
            price_str = f"Glass €{item['price_glass']:.2f} / Bottle €{item['price_bottle']:.2f}"
        if "price_small" in item:
            price_str = f"Small €{item['price_small']:.2f} / Large €{item['price_large']:.2f}"

        item_text = (
            f"{item['category'].upper()} — {item['name']} ({item.get('name_de', '')}): "
            f"{item['description']} "
            f"Price: {price_str}. "
            f"Allergens: {allergen_str}. "
            f"Tags: {', '.join(flags) if flags else 'none'}."
        )
        if item.get("note"):
            item_text += f" Note: {item['note']}."

        docs.append(item_text)
        ids.append(f"item_{item['id']}")
        metadatas.append({
            "type": "menu_item",
            "category": item["category"],
            "item_id": item["id"],
            "name": item["name"],
            "price": float(price),
            "vegan": str(item.get("vegan", False)),
            "vegetarian": str(item.get("vegetarian", False)),
            "halal": str(item.get("halal", True)),
        })

    # Weekly specials
    for special in menu_data.get("specials", {}).get("weekly", []):
        allergen_str = ", ".join(special.get("allergens", [])) if special.get("allergens") else "none"
        special_text = (
            f"WEEKLY SPECIAL ({special['day'].title()}) — {special['name']}: "
            f"{special['description']} Price: €{special['price']:.2f}. "
            f"Allergens: {allergen_str}."
        )
        docs.append(special_text)
        ids.append(f"special_{special['day']}")
        metadatas.append({"type": "special", "category": "special", "day": special["day"]})

    return docs, ids, metadatas


def build_index():
    print("Loading menu data...")
    menu_data = load_menu()

    print("Building documents...")
    docs, ids, metadatas = build_documents(menu_data)
    print(f"  → {len(docs)} documents prepared")

    print("Initialising ChromaDB...")
    # Wipe the entire directory so no stale _type schema files remain.
    # delete_collection() alone leaves SQLite/parquet artifacts that cause
    # a KeyError '_type' on the next PersistentClient() call in v0.5.x.
    if os.path.exists(CHROMA_PATH):
        shutil.rmtree(CHROMA_PATH)
        print(f"  → Wiped existing chroma_db at {CHROMA_PATH}")

    client = chromadb.PersistentClient(path=CHROMA_PATH)

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    collection = client.create_collection(
        name="restaurant_knowledge",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )

    print("Indexing documents...")
    # Batch in chunks of 50 to avoid memory spikes
    batch_size = 50
    for i in range(0, len(docs), batch_size):
        batch_docs = docs[i:i + batch_size]
        batch_ids = ids[i:i + batch_size]
        batch_meta = metadatas[i:i + batch_size]
        collection.add(documents=batch_docs, ids=batch_ids, metadatas=batch_meta)
        print(f"  → Indexed {min(i + batch_size, len(docs))}/{len(docs)}")

    print(f"\nIndex built successfully.")
    print(f"  Collection: restaurant_knowledge")
    print(f"  Documents:  {collection.count()}")
    print(f"  Path:       {CHROMA_PATH}")


if __name__ == "__main__":
    build_index()
