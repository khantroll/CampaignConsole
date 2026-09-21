def search_campaign_text(query: str, items, fields):
    lower_query = query.lower()
    matches = []

    for entry in items:
        text_pieces = []
        for field in fields:
            value = getattr(entry, field, None)
            if value:
                text_pieces.append(str(value))
        combined = " ".join(text_pieces)
        if lower_query in combined.lower():
            matches.append({
                "title": getattr(entry, fields[0], "Result"),
                "subtitle": " | ".join(str(getattr(entry, field, "")) for field in fields[1:]),
                "snippet": combined[:180] + ("..." if len(combined) > 180 else ""),
            })
    return matches
