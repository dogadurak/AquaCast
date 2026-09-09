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
durum: BEKLEMEDE -> OK
REVIZE: ilk kayit alan farki nedeniyle durmustu. Kullanici karariyla uyelik
  satir filtresi degil KOLON yapildi (in_hydrobasins, in_akarcay_lobe), boylece
  sinir revizyonu re-export degil config degisikligi. Gorev tamamlandi; asagida
  guncel kayit.
durum (ilk): BEKLEMEDE (durma kosulu tetiklendi)
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

## T1 - havza sinari + analiz gridi (tamamlandi)
durum: OK
artefakt: data/interim/grid_cells.csv (2820 hucre), data/interim/grid.geojson
  (1.3 MB), reports/figures/basin_boundary_uncertainty_{light,dark}.png
assert: 16 invariant, hepsi tuttu. Onemli olanlar:
  - grid hizalamasi: |i-round(i)| beklenen <1e-6 -> gercek 0.00e+00
  - cell_id lon/lat'tan yeniden hesaplanip karsilastirildi -> birebir
  - cell_id tekil: beklenen 2820 -> gercek 2820
  - WorldCover no-data hucre: beklenen 0 -> gercek 0
  - in_hydrobasins: beklenen 2395 -> gercek 2395 (+0.00%)
  - maskeli (crop_frac_2021>=0.5): beklenen 2130 -> gercek 2130 (+0.00%)
  - alan orani vs hucre orani: beklenen 0.8613 -> gercek 0.8605 (fark 0.0008)
  - dusuk-crop hucreler KORUNDU (filtrelenmedi) -> dogrulandi
sure: ~1.5 sa (arastirma + iki kod hatasi + figur yerlesimi)
surpriz: buyuk olani. HydroBASINS L5 poligonu TEK bir kapali havza degil, DOKUZ
  ayri endorheic sink'in birlesimi. +17.2%'lik fazlaligin tamami pratikte tek bir
  lob: MAIN_BAS 2060086420, 8096 km2, 30.00-31.83E / 38.06-39.13N. Bu Aksehir-Eber
  golleri, yani AKARCAY kapali havzasi - Bakanligin komsu havza olarak listeledigi
  havza (yayinlanmis Akarcay alani ~7400 km2). Cikarinca 50278 km2 = resmi tabloya
  gore +0.50%. Diger sekiz alt havzanin hicbiri %7.5'ten yakin degil.
  Yani fark DELINEASYON GURULTUSU DEGIL, TANIM FARKI - savunulabilir ve
  aciklanabilir. Vektor alan orani (0.8613) ile raster hucre orani (0.8605)
  bagimsiz yollarla %0.08 farkla ortusuyor.
  Ikinci surpriz: kendi yazdigim failure-mode #13'e dustum (worldcover_gap_count
  icinde 10m -> 0.05 derece tek adimda indirgeme, 360001 piksel vs 4000 tavan).
  Ucuncusu: figurun ilk halinde baslik/altyazi/lejant catismasi ve tasma vardi -
  "render edip bak" adimi olmasa sessizce bozuk gidecekti.
acik varsayim: Akarcay tespiti alan + cografya kanitina dayali HIPOTEZ; resmi
  poligon elde degil, geometri karsilastirmasi yapilmadi. Fark figuru bu yuzden
  HydroBASINS'i ayristiriyor, resmi sinirdan cikarmiyor.
sonraki: T2 (CHIRPS export) - membership_column secimi kullaniciya soruldu
