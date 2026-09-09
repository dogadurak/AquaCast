# Phase 0 log

Append-only. One entry per task, in the format defined in `docs/working_protocol.md`.
If a past task's output is changed later, add a `REVİZE:` line to that task's entry
rather than editing it silently.

## T0 — kurulum ve veri erişimi
durum: OK
artefakt: reports/data_access.json, .venv, git repo (4 commit)
assert: CORE veri setleri çözümlendi → CHIRPS v3 1981-01→2026-07 ✓,
  ERA5-Land 1950-02→2026-08 ✓, MOD13A2 2000-02→2026-08 ✓; blocker sayısı
  beklenen 0 → gerçek 0 ✓
süre: ~1 sa
sürpriz: check_data_access.py'de üç bug. En ciddisi ERA5-Land'i sahte blocker
  olarak raporlaması (1950 başlangıcı → negatif timestamp → Windows'ta OSError).
  GRACE V04/LAND yeşil [OK] görünürken kaydı 2017-05'te bitiyordu; MASCON_CRI'ye
  geçildi (2024-09) ve kapsam kontrolü eklendi. Spec'te iki çelişki bulundu ve
  düzeltildi: 1991-2020 referans dönemi (leak) ve 1 km grid vs ~2000 hücre
  aritmetiği (çözünürlük şişirmesi).
sonraki: T1

## T1 - havza sinari + analiz gridi
durum: BEKLEMEDE (durma kosulu tetiklendi)
artefakt: yok - grid uretilmedi
assert: bagimsiz alan karsilastirmasi -> resmi (SYGM) 49805.3 km2 vs
  HydroBASINS L5 58373.7 km2 = +%17.2. Kullanici esigi %10. DURDU.
sure: ~25 dk (arastirma + probe)
surpriz: iki tane. (1) HydroBASINS poligonu batida 30.004 derece E'ye
  uzaniyor, config AOI bbox'in bati kenari 31.4 - poligon bbox'i 1.4 derece
  asiyor, yani bbox bir filtre olarak kullanilsaydi havzanin bir seridi
  sessizce dusecekti. (2) hybas_6 kirilimi bolgeyi TEK bir kapali havza
  olarak degil, farkli MAIN_BAS id'lerine sahip AYRI kapali havzalar olarak
  tanimliyor; L5 bunlari birlestiriyor. Dogru alt kumeyi resmi sinir olmadan
  secmek tahmin olurdu.
sonraki: kullanici karari bekleniyor - sinir kaynagi secilecek
