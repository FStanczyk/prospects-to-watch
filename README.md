# Prospects to Watch

Lista prospektów do draftów NHL 2027–2029 z numerami na koszulkach – wybierasz ligę i dwie drużyny, widzisz na kogo patrzeć.

## Aktualizacja danych

1. Zapisz tabele z [EP Draft Center](https://www.eliteprospects.com/draft-center) jako `data/2027prospects.html`, `data/2028prospects.html`, `data/2029prospects.html`.
2. `python3 fetch_prospects.py` – numery z oficjalnych składów OHL/WHL/QMJHL/USHL(+NTDP).
3. Brakujące numery dopisz w `data/manual_numbers.json` (`"ep_id": "numer"`) i uruchom skrypt ponownie.
4. `git commit -am "update" && git push`
