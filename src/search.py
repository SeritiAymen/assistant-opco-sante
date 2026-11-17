import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

DATA_DIR = Path("data")
EVAL_DIR = Path("eval")
TOP_K = 3


def tokenize(text):
    text = text.lower()
    return re.findall(r"\w+", text)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def search(bm25, chunks, query, k=TOP_K, sector=None):
    scores = bm25.get_scores(tokenize(query))

    ranked = scores.argsort()[::-1]

    if sector is not None:
        ranked = [i for i in ranked if chunks[i]["sector"] == sector]

    return [(chunks[i], scores[i]) for i in ranked[:k]]


def first_correct_rank(results, expected_chunks):
    for rank, (chunk, _score) in enumerate(results, start=1):
        if chunk["chunk_id"] in expected_chunks:
            return rank
    return None


def main():
    chunks = load_json(DATA_DIR / "processed" / "chunks.json")
    questions = load_json(EVAL_DIR / "questions.json")

    tokenized_chunks = [tokenize(c["text"]) for c in chunks]
    bm25 = BM25Okapi(tokenized_chunks)

    found_count = 0
    for q in questions:
        results = search(bm25, chunks, q["question"], sector=q.get("sector"))
        rank = first_correct_rank(results, q["expected_chunks"])
        is_found = rank is not None
        print(
            f"{q['id']} | secteur : {q.get('sector')} | Trouvé : {is_found} | rang : {rank}"
        )

        for chunk, score in results:
            print(f"{chunk['chunk_id']:<16} {score:.2f}")
        print("\n============================================\n")

        if is_found:
            found_count += 1
    print(f"Résultats trouvés : {found_count}/{len(questions)}")


if __name__ == "__main__":
    main()
