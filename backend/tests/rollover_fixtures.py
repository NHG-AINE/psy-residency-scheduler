from copy import deepcopy

from tests.test_requirement_ledger import resident


def following_year(book, generated, recorded_year):
    """Record generated postings and leave as workbook cells for the next draft."""
    following = deepcopy(book)
    history = []
    for month in generated:
        if month["status"] == "loa":
            history.append((month["month"], "LOA"))
        elif month["status"] == "posting":
            marker = " (Elective)" if month["target"]["category"] == "elective" else ""
            history.append((month["month"], month["label"] + marker))
    following["annual_sheets"].append({"residents": [resident(history, recorded_year, f"Previous {recorded_year}")]})
    following["target_year"] += 1
    for month, cell in zip(following["months"], following["residents"][0]["postings"]):
        month["month"] = str(int(month["month"][:4]) + 1) + month["month"][4:]
        cell.update(month=month["month"], status="blank", value=None)
    following["requests"] = []
    return following
