# Prospects to Watch

Lista prospektów do draftów NHL 2027–2029 z numerami na koszulkach – wybierasz ligę i dwie drużyny, widzisz na kogo patrzeć.

## Aktualizacja danych

1. Zapisz tabele z [EP Draft Center](https://www.eliteprospects.com/draft-center) jako `data/2027prospects.html`, `data/2028prospects.html`, `data/2029prospects.html`.
2. `python3 fetch_prospects.py` – numery z oficjalnych składów OHL/WHL/QMJHL/USHL(+NTDP) oraz terminarz meczów tych lig na 60 dni naprzód (`data/schedule.js`, zakładka „Kalendarz”). Terminarz warto odświeżać co tydzień.
3. Brakujące numery wpisz w kolumnie `numer` w `data/manual_numbers.csv` i uruchom skrypt ponownie (nowi zawodnicy bez numeru dopisują się tam sami).
4. `git commit -am "update" && git push`
