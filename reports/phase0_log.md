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

## T2 - CHIRPS export (tamamlandi)
durum: OK
artefakt: data/raw/chirps/chirps_1981..2025.csv (45 dosya + 45 manifest),
  reports/chirps_continuity.json, reports/chirps_bias.json,
  reports/figures/chirps_continuity_{light,dark}.png
assert: hepsi gecti.
  - yil dosyasi: beklenen 45 -> gercek 45
  - toplam satir: beklenen 1.522.800 -> gercek 1.522.800
  - her ay tam 6 pentad (koleksiyon) VE piksel basina n_obs=6 (kismi maskeleme yok)
  - havza-ort yillik: export vs on kontrol, her yil %0.1 altinda
    (or. 1981 595.9 vs 595.4 = +0.07%; 1982 390.4 vs 390.3 = +0.04%)
  - izole-sifir orani: beklenen <=1% -> gercek 0.0347% (529 satir)
sure: ~3 sa (kesintiler + iki assert duzeltmesi dahil)
surpriz: dort tane.
  (1) On kontrol: V3 PENTAD'da kaynak/versiyon bayragi YOK, sadece year/month/
      pentad. Urun hatti degisikligi metadata'dan tespit edilemiyor. Zaman
      serisinde basamak yok; 2022-2025 era ortalamasi dusuk ama 2023 = 467 mm
      uzun donem ortalamasinin USTUNDE, yani seviye kaymasi degil. 2025 (287 mm)
      45 yilin en kurak yili. Prelim sorusu CHC dokumantasyonundan kapatildi:
      final, takip eden ayin ucuncu haftasinda; 2025-12'nin final'i ~2026-01-20,
      bu calistirmadan sekiz ay once. Panele prelim girmiyor.
  (2) Sifir testini UC kez yazdim, ilk ikisi yanlisti. v1 grid geneli (cok kaba,
      1986-05'i kacirdi), v2 hucre komsulugu (kurak ayda tersine dondu, 1990-03'te
      2009 gercek sifirin 1882'sini "izole" saydi), v3 kume sinir minimumu
      (dogru mekanizma: gercek kuraklik gradyan, artefakt ucurum).
  (3) 417 mm esigi kategori hatasiydi: havza-ORTALAMA YILLIK degeri tek hucrenin
      AYLIK degerine sinir yapmisim, ustelik halka hucrelerine de uygulamisim.
      720.6 mm'lik deger gercekti - Toros yamacinda, havza disinda bir halka
      hucresi. Yerine iki bagimsiz hesap yolunun karsilastirmasi kondu.
  (4) BIAS BULGUSU + beklenmedik dogrulama: CHIRPS havza-ort yillik 463.2 mm vs
      resmi 417 mm = +%11.1. Ama Akarcay lobu cikarilinca +%7.7'ye iniyor.
      Akarcay daha bati, daha Akdeniz etkisinde, daha yagisli. T1'de ALAN
      aritmetiginden cikan "Akarcay buraya ait degil" sonucu, burada YAGIS
      klimatolojisinden bagimsiz olarak dogrulandi. Aranmadi, cikti.
acik varsayim: CHIRPS final urunleri yeniden isleniyor; her yil dosyasinin
  manifest'inde fetched_utc var, sonraki bir farklilik atfedilebilir olsun diye.
sonraki: T3 (ERA5-Land export) calisiyor

## T3 - ERA5-Land export (devam ediyor)
durum: DEVAM
artefakt: data/raw/era5/era5_<yil>.csv (calisiyor), reports/station_cells.json
assert (1990 test yili): hepsi gecti.
  - farkli deger orani (bilinear vs nearest): beklenen >=0.90 -> gercek 1.000
    (nearest ~0.25 verirdi; 0.05 derece gridi gercekten test eden tek kontrol)
  - ERA5 vs CHIRPS 1990: 358 vs 351 mm = +%2.0 (tolerans %35)
  - fiziksel invariantlar: tmin<=t2m<=tmax ve dewpoint<=t2m, 0 ihlal
  - su maskesi: 0 nodata hucre (ERA5-Land Tuz Golu'nu kara sayiyor)
  - ERA5 yerli piksel: 756 adet, 2820 hucre icin ~3.7 hucre/piksel
surpriz: uc tane.
  (1) MONTHLY_AGGR'in temperature_2m_max/min'i ayin TEKIL SAATLIK ucu, ortalama
      gunluk uc degil. 1990-07 Konya: MONTHLY 34.08/12.59, gercek ort. gunluk
      30.34/16.97. (Tmax-Tmin) %61 sisik, Hargreaves ET0 %27 yuksek cikardi.
      FAO-56 de ayni girdiyi istedigi icin bu bant her iki yontemi de bloke etti.
      Cozum: DAILY_AGGR ay ortalamasi -> 30.34/16.97 birebir, ayda 31 goruntu.
  (2) MONTHLY_AGGR ile DAILY_AGGR'in temperature_2m'i AYNI DEGIL: ortalama fark
      -0.40/-0.23 C ama hucre bazinda 4.4/5.9 C'ye kadar. Karistirinca 255 satir
      t2m<[tmin,tmax] disinda, 107 satir dewpoint>t2m cikti. Sicaklik ailesinin
      tamami DAILY_AGGR'a cekildi, invariantlar rahat marjla gecti.
  (3) Ruzgar: dogrudan hiz bandi yok. Aylik u,v'nin hypot'u vektorel ortalamanin
      buyuklugu - gercek skaler ortalamaya gore -%14.9. Gunluk hypot -%8.6.
      Gunluk kullanildi, kalan sapma limitasyon olarak yazildi (HOURLY 24 kat
      compute, ikinci mertebe degiskende ikinci mertebe duzeltme).
acik varsayim: istasyon koordinatlari benim tahminim, MGM'nin resmi degerleri
  degil. Karaman (2.12 km) ve Beysehir (2.02 km) hucre merkezine uzak, birkac
  km'lik duzeltme komsu hucreye tasiyabilir. Normaller gelince yeniden hesaplanacak.
sonraki: export bitince T3 kapanacak, sonra T4 (panel birlestirme)

## ACIK ISLER - iki kategori, karistirilmayacak

FAZ 0'IN KAPISI TEK BIR SORU: model climatology'yi, persistence'i ve
known-accumulation baseline'ini yeniyor mu, ne kadar? O karsilastirma tamamen
IC - model de baseline'lar da ayni paneli kullaniyor. Dis referanslarin hicbiri
skill tablosunu degistirmez.

### A - FAZ 0 KAPISINI BLOKLAYAN (hicbiri dis veri gerektirmiyor)
- [ ] T4 panel birlestirme (kod hazir, CHIRPS yeniden cekimini bekliyor)
- [ ] T5 SPI-1 ve SPI-3 + climate_indices dogrulamasi
- [ ] T6 dort baseline (model YAZMADAN ONCE)
- [ ] T7 XGBoost: SPI-3 @ +3 ay (birincil), SPI-1 @ +1 ay (ikincil)
- [ ] T8 skill tablosu + /leakage-audit + /phase-gate

KAPSAM TAAHHUDU: T5-T8 arasinda kapsam BUYUTULMEYECEK. Bulunan her ilginc sey
otomatik olarak bir gorev degildir - B'ye yazilir ve devam edilir. Skill tablosu
ciktiktan sonra model card istenildigi kadar zenginlestirilir. Bu projenin
gecmisindeki tekrar eden hata tema degistirmek degil, sonuca varmadan
derinlesmek; titizlik sonucu erteleyen bir forma burunebilir.

### B - MODEL CARD ICIN, KAPIDAN SONRA (hicbiri A'yi bekletmiyor)
- [ ] MGM istasyon karsilastirmasi: ERA5 sicaklik dogrulamasi (nokta bazli)
- [ ] MGM istasyon karsilastirmasi: CHIRPS yagis dogrulamasi
      (417 mm anchor'i coktu - iki eksende eslesmiyor, bkz. commit gunlugu)
- [ ] SPI guvenilirlik esiginin kalibrasyonu (su an PROVISIONAL 5 mm, bin'ler
      betimleyici; skill tablosu bunlara BAGLI DEGIL)
- [ ] DSI resmi havza siniri -> in_official kolonu (uyelik kolonu kalibi
      sayesinde config degisikligi, yeniden export degil)
- [ ] Konya Havzasi Kuraklik Yonetim Plani'ndaki resmi esiklerle karsilastirma
- [ ] PET uc yol karsilastirmasi: FAO-56 vs ERA5 pev vs Hargreaves
- [ ] Akarcay bulgusunun figuru (uretildi) model card'a

### Teknik borc (A'yi bloklamiyor, unutulmasin diye burada)
- [x] PET esikleri 45 yildan siklastirildi (0.989 / -3.0 mm)
- [x] ERA5 vs CHIRPS korelasyonu: 45 yil, r = 0.809
- [ ] T4'te: tarih anahtari KUME esitligi, outer join + hucre kumesi kontrolu,
      provenans KOD AGACI hash'i (ham SHA degil), satir sayisi tam 1.522.800
- [ ] T5'te: FAO-56 ET0 sifirda kirpilacak + *_clamped bayragi
- [ ] T5'te: kok bolgesi nemi DERINLIK AGIRLIKLI 0.07/0.21/0.72, duz ortalama YASAK

## T4 - panel birlestirme (tamamlandi)
durum: OK
artefakt: data/processed/panel_monthly.parquet (1.522.800 satir x 35 kolon,
  227.2 MB), reports/panel_integrity.json
assert: hepsi gecti, uc kusur bulunup duzeltildikten sonra.
  - provenans: chirps digests=[tek deger] shas=4 dirty_producers=0
               era5   digests=[tek deger] shas=2 dirty_producers=0
  - tarih/hucre KUME esitligi (chirps vs era5 vs grid): True
  - outer join, satir: beklenen 1.522.800 -> gercek 1.522.800
  - deger checksum (join yapmadan, kaynak vs panel): 24 kolon, 0 uyusmazlik
  - precip_zero_isolated: beklenen 529 -> gercek 529
sure: ~40 dk (ilk kosu + uc kusur + duzeltme)
surpriz: ilk kosu "hepsi OK" bastı ama UC AYRI KUSUR ta$iyordu, hicbiri
  hata firlatmadi:
  (1) provenans check'i `problems` listesini dolduruyordu ama hic `ok`'a
      baglanmamisti - assert var, KAPI yoktu. ERA5 manifest'lerinde
      producer_digest hic yoktu (mekanizma sonradan eklendi) ve bu sessizce
      gecti. Git nesnelerinden geriye donuk hesaplanip damgalandi.
  (2) git_dirty bayragi COK KABA: CHIRPS 1982 ".claude/skills/... ve
      CLAUDE.md degisti" diye kirli isaretlenmisti ama bunlar URETICI
      DOSYA degil - producer_digest 44 digerinden farksizdi. Bayrak artik
      SADECE producers listesindeki dosyalar degistiyse ateşliyor.
  (3) zero_diagnostics() panelde `groupby("month")` ile cagrilinca 45 yili
      TEK takvim ayina eziyordu (126.900 satir -> 2.820 anahtar, dict son
      yili tutuyordu), 0 izole hucre bulup sessizce gecti. groupby("date")
      olarak duzeltildi - export'ta (tek yil) ve panelde (45 yil) ayni
      davranisi verir.
acik varsayim: yok - T4'un tum acik maddeleri (tarih/hucre kume esitligi,
  outer join, provenans kod agaci) bu kosuda kapatildi.
sonraki: T5 (SPI hesaplama) - hedef tanimi onceki oturumda karara baglandi:
  SPI-3 birincil, SPI-1 ikincil+takvim-ayi-bazinda. Kapsam BUYUMEYECEK.

## T5 on-kontrol - "1991-2020" iddiasi dogrulanamadi
durum: DUZELTME GEREKMEDI (iddia yanlisti, kontrol edildi, kayitli)
Kullanici T5'in PLAN'ini onaylarken CLAUDE.md ve PROJECT_SPEC.md'de hala
"1991-2020" gectigini ve bunun train/test split'iyle (2001-2016) ve MODIS'in
2000 baslangiciyla celistigini iddia etti; tek 1981-2016 penceresi onerdi.

grep ile dogrulandi: "1991-2020" hicbir dosyada YOK. Bulunan tek eslesmeler o
donemi REDDEDEN gecmis-zaman ifadeleri ("supersedes", "corrects the draft
spec", "cannot be used here") - duzeltme onceki bir turda zaten yapilmisti
(commit d4936de, "fix: replace unusable 1991-2020 reference period...").

Onerilen TEK pencere de (1981-2016, her sey icin) kullanicinin kendi daha once
belirttigi sorunu yeniden uretirdi: ndvi_anom icin fiziksel olarak imkansiz,
MODIS 2000'den once yok. Mevcut tasarim zaten IKI ayri pencere kullaniyor:
  baseline_precip_era5 (1981-2016) -> SPI, sm_anom, ERA5 turevleri
  baseline_modis       (2001-2016) -> ndvi_anom, lst_anom
Ikisi de train donemini asmiyor, ikisi de validation/test'e sizmiyor.

Aksiyon: dosyalarda degisiklik yok (zaten dogru). CLAUDE.md'ye eksik olan iki
kontrat satiri eklendi: spi1_mm_per_unit, spi3_mm_per_unit (MODIS'in "Faz 1"
desenindeki gibi - tasarim karari olarak kayitli, henuz uretilmedi).
Bu vakayi kaydetme sebebi: iddia gecerli olsaydi spec'i etrafindan dolanmadan
duzeltecektim (CLAUDE.md working style kurali); gecerli olmadigi icin de ayni
titizlikle KONTROL EDILDIGI ve NEDEN aksiyon alinmadigi kayit altina alinmali -
sessizce atlanan bir talep, kontrolun hic yapilmadigi izlenimini verir.
sonraki: T5 - src/features/spi.py
