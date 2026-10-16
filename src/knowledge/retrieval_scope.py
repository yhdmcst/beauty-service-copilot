"""Build retrieval scope from explicit structured records, never product-name guesses."""

def retrieval_scope(context: dict, focus: str) -> dict:
    result = {"analysis_at": context.get("analysis_at", ""), "service_focus": focus}
    orders = [item.get("fields", {}) for item in context.get("evidence", [])
              if item.get("type") == "order"]
    for key, aliases in {"brand": ("brand", "品牌"),
                         "product_id": ("product_id", "商品货号"),
                         "channel": ("channel", "渠道")}.items():
        explicit = context.get(key)
        if isinstance(explicit, str) and explicit:
            result[key] = explicit
        elif orders:
            values = [{str(row[a]) for a in aliases if row.get(a)} for row in orders]
            if all(len(value) == 1 for value in values) and len(set.union(*values)) == 1:
                result[key] = next(iter(values[0]))
    return result
