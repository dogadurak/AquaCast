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

## T5 - SPI-1 ve SPI-3 (tamamlandi)
durum: OK
artefakt: data/processed/panel_monthly.parquet (+4 kolon: spi_1, spi_3,
  spi1_mm_per_unit, spi3_mm_per_unit), reports/spi_validation.json
assert: hepsi gecti.
  - satir: beklenen 1.522.800 -> gercek 1.522.800
  - spi_1/spi_3 araligi: [-4,4] icinde
  - spi_3 null: beklenen 5640 (2 ay x 2820 hucre, akumulasyon isinmasi) -> gercek 5640
  - spi_1 null: beklenen 0 -> gercek 0
  - elle 3-aylik toplam vs vektorlestirilmis rolling sum: birebir esit
  - climate_indices REFERANS UYGULAMAYLA tam seri (540 ay, 3 hucre) karsilastirma:
    maks|fark| = 0.00e+00 (esik <1e-9)
sure: ~20 dk (iki kod hatasi dahil)
surpriz: iki kod hatasi, ikisi de kendi yazdigim kod:
  (1) _rolling_sum'da kayan pencere aritmetigi hatali - csum'u IKI KEZ ayri
      dilimliyordum, genislikler 538 vs 536 uyusmadi, SPI-3 hesaplanmadan
      cokme. csum'u k kadar SAGA KAYDIRIP (sifir dolgulu) TEK dilimde
      cikarma olarak duzeltildi.
  (2) climate_indices karsilastirmasinda "~0" string'ini "0.00e+00" ile
      essitlik testi yapmisim - hicbir zaman esit olamaz, gercek sonuc
      (fark tam 0) yanlislikla MISMATCH olarak raporlandi. Say1sal esik
      testine (worst<1e-9) cevrildi.
  Ucuncusu kod hatasi degil ama not edilmeli: spi1_mm_per_unit Ocak ayinda
  bu oturumda 23.7 mm cikti, onceki oturumun ad-hoc (commit edilmemis)
  olcumu 19.2 demisti - 11/12 ay birebir eslesirken sadece Ocak sapiyor.
  Cift bagimsiz dogrulama yapildi: (a) climate_indices'e karsi tam seri
  karsilastirmasi 0.00e+00 verdi, (b) panelden SIFIRDAN yazilan ayri bir
  script ayni 23.7'yi uretti. Mevcut sonuc guvenilir; onceki ad-hoc script
  kaybolmus ve kucuk bir farkli olabilir, arastirilmadi (dusuk oncelik,
  Faz 0 kapisini etkilemiyor).
acik varsayim: yok. climate_indices dogrulamasi TAM SERI uzerinde (orneklem
  degil) yapildi - T4'un checksum dersi burada da uygulandi.
sonraki: T6 (dort baseline, MODEL YAZMADAN ONCE)

## T6 - dort baseline (tamamlandi)
durum: OK
artefakt: data/processed/baselines_monthly.parquet (3.045.600 satir = 2 hedef x
  1.522.800), reports/baselines_summary.json
assert: hepsi gecti.
  - satir: beklenen 3.045.600 -> gercek 3.045.600
  - climatology fit'i test donemine (2022+) ekilen sentinel degerden (999999)
    ETKILENMEDI - zehirli deger ile temiz veri birebir ayni cikti
  - persistence: elle (hucre,tarih) bakisi ile forecast[t]==actual[t-lead] dogrulandi
  - known_accumulation == climatology (BAGIMSIZ kod yollarindan): spi_3@+3 VE
    spi_1@+1 icin True - iki hedefte de beklenen sonuc alindi
  - C3S satiri her hedef icin VAR, degeri null (erisim bekliyor) - sessizce
    atlanmadi
sure: ~20 dk
surpriz: iki sey.
  (1) load_config() varsayilan olarak config/data.yaml okuyor, targets/baselines
      config/model.yaml'da - ilk kosu KeyError verdi. Iki config ayri okunacak
      sekilde duzeltildi.
  (2) test_known_accumulation_baseline_matches_climatology_numerically (T0'da
      yazilmis, o zaman src.models.baselines yoktu) climatology_forecast(name,
      lead) imzasi varsayiyordu - ben ise leakage guvenligi icin panel ve
      fit_start/fit_end'i ACIK PARAMETRE yaptim (spi.py'deki fit/apply ayrimiyla
      ayni disiplin). Test gercek imzaya guncellendi, kontrolun KENDISI
      zayiflatilmadi - hala iki bagimsiz kod yolunu gercek panel uzerinde
      karsilastiriyor. 8/10 test geciyor artik (2 skip Faz 2/3 icin dogru
      sekilde bekliyor).
acik varsayim: yok. sm_anom henuz panelde olmadigi icin (Faz 2) otomatik
  filtrelendi - dogru davranis, hata degil.
sonraki: T7 (XGBoost: spi_3 @ +3 birincil, spi_1 @ +1 ikincil)

## T7 on-kontrol - ucuncu dogrulama, ayni sonuc
durum: DEGISIKLIK GEREKMEDI (uc kez ayni sonuc)
"1991-2020" ve spi1_mm_per_unit/spi3_mm_per_unit sorulari bu oturumda UCUNCU
kez soruldu (T5 oncesi, T6 oncesi, simdi T7 oncesi). Taze grep ile yine
dogrulandi: "1991-2020" hicbir dosyada yok (duzeltme commit d4936de), kontrat
satirlari yerinde (commit c6f6d62). Ayrica istenen ucuncu kontrol - spi_1/spi_3
icin 'kind' alaninin config'te ACIK olup olmadigi - dogrulandi: ikisi de acik
(spi_3: classification, spi_1: regression, commit c84d2df'de yazilmis), ek
islem gerekmedi.

NEDEN BURAYA YAZILIYOR: ayni sorunun ucuncu kez sorulmasi, onceki iki
dogrulamanin karsi tarafa (baska bir oturum/baglam) ulasmadigini gosteriyor.
Cozum aksiyon degil - dosyalar zaten dogru - ama tekrar eden dogrulama
maliyetini azaltmak icin: bundan sonra boyle bir soru gelirse once bu log
girdisine ve ilgili commit SHA'larina (d4936de, c6f6d62, c84d2df) isaret
edilecek, sifirdan grep yerine.
sonraki: T7 - src/models/train.py

## T7 - XGBoost (tamamlandi)
durum: OK
artefakt: data/processed/predictions.parquet (1.545.360 satir), src/features/build.py
  (feature insasi, mimari nedenle src/models/ yerine buraya tasindi),
  reports/training_summary.json
assert: hepsi gecti.
  - future-reference kaniti (sentinel testi): gelecekten sizinti yok
  - split satir sayilari (hucre x ay formulu): train/val/test ucu de birebir
  - train'in son etiketi (lead kaydirmali) validation'dan once kaliyor
  - gap uzunlugu en uzun lead'i (+3) kapsiyor
  - test doneminde spi_3 null: 0 (warm-up etkisi 1981'de, test'e degmiyor)
  - spi_3: actual ikili {0,1}, prediction [0,1] olasilik - AYRI kontrol
sure: ~35 dk (iki gercek bug + bir kalibrasyon adimi dahil)
surpriz: T8'e gecmeden yapilan saglama kontrolunde IKI gercek bug bulundu,
  ikisi de kod hatasi:
  (1) siniflandirma hedefinde (spi_3) cikti tablosuna `actual` olarak HAM SPI
      degeri yaziliyordu, oysa egitim ve prediction ikili gostergeye (y_all,
      SPI<-1) gore yapiliyordu. Egitimin kendisi dogruydu, sadece raporlama
      kolonu yanlisti - T8'in AUC/Brier hesabini sessizce bozacakti. actual
      artik y_all (karsilastirilabilir buyukluk), actual_raw_spi ayri kolon.
      Yeni bir assert eklendi: siniflandirma hedefinde actual ikili, prediction
      [0,1] icinde.
  (2) XGBoost early_stopping_rounds OLMADAN 300 agaci kosulsuzca fit ediyordu.
      Ilk kosuda spi_1 RMSE (1.07) test doneminin kendi ortalamasindan (std=
      0.898) bile kotu cikti - train donemine (2001-2016) asiri uyup iklimi
      farkli test donemine (2022-2025, en kurak yil 2025 dahil) kotu genelleme
      yapiyordu. early_stopping_rounds=20 eklendi (validation setine gore) -
      bu bir hiperparametre aramasi degil, "calisan sikici" TEK konfigurasyon
      karari. Sonrasinda RMSE 1.03'e dustu.
  Kalan durum arastirildi, bug degil: XGBoost (1.033) climatology'yi (0.917,
  DOGRU kiyas noktasi - 1981-2016'dan fit) hafifce geçemiyor ama persistence'tan
  (1.165) iyi - tutarli bir siralama. Ilk "trivial ortalamadan kotu" alarmi
  test doneminin KENDI ortalamasiyla kiyaslamaktan kaynakliydi, adil bir
  karsilastirma degildi; climatology dogru kiyas noktasi.
acik varsayim: yok. Faz 0'in kisitli feature seti (MODIS/SPEI/C3S yok) ile
  spi_3@+3 spec'in Problem 2 uyarisini test ediyor - ilk bakis: AUC 0.4847
  (rastgeleden kotu), Brier model 0.1968 vs climatology 0.1851 (model daha
  kotu). Bu beklenen, raporlanabilir sonuc. Tam skill tablosu T8'de.
sonraki: T8 (skill tablosu + /leakage-audit + /phase-gate) - Faz 0'in KAPI
  sorusunun cevabi

## T8 - skill tablosu (tamamlandi) - FAZ 0 KAPI SORUSUNUN CEVABI
durum: OK
artefakt: reports/skill_table.md, reports/metrics_<timestamp>.json (git SHA dahil),
  src/models/baselines.py'a olasilik-bicimli baseline'lar eklendi (T6 reopened,
  kullanicinin onayiyla, mimari nedenle skill.py'a degil baselines.py'a)

HEADLINE SONUC (analiz populasyonu: 1.823 hucre, in_hydrobasins & ~in_akarcay_lobe
& crop_frac>=0.5; test 2022-2025; metrikler tarih bazinda hesaplanip ORTALAMA
alinarak ozetlendi, satir havuzlanmadi):

  spi_3 @ +3 (BIRINCIL, siniflandirma, 35 gecerli tarih/45):
    model         AUC 0.4904  Brier 0.2113
    climatology   AUC 0.5129  Brier 0.2039   BSS(model vs bunu) = -0.036
    persistence   AUC 0.4826  Brier 0.3391   BSS(model vs bunu) = +0.377
    known_accum   = climatology (beklendigi gibi, overlap=0)
    c3s_raw       N/A (CDS erisimi bekliyor)

  spi_1 @ +1 (IKINCIL, regresyon, 47 tarih):
    model         MAE 0.7842  RMSE 0.8861
    climatology   MAE 0.6988  RMSE 0.7915   skill(RMSE) = -0.120
    persistence   MAE 0.8904  RMSE 1.0278   skill(RMSE) = +0.138
    known_accum   = climatology (beklendigi gibi, overlap=0)
    c3s_raw       N/A

SENTEZ: Model HER IKI hedefte de persistence'i aciyla yeniyor ama climatology'yi
gecemiyor. spi_3@+3 icin bu PROJECT_SPEC Problem 2'nin ONCEDEN kayit altina
alinmis, beklenen sonucu - lag-only feature'larla 3 ay oteye tahmin edilemez.
spi_1@+1 icin bu ONCEDEN BEKLENMEYEN bir bulgu: PROJECT_SPEC 2.1 "Tier 1...
should reach meaningful skill" diyor, ama Faz 0'in kasitli olarak minimal
feature seti (MODIS NDVI/LST yok, derinlik-agirlikli toprak nemi anomalisi yok,
SPEI yok) ile model climatology'yi +1 ayda bile gecemiyor. Bu Tier 1'in
kurtarilamaz oldugu anlamina gelmez - Faz 1/2'nin tam feature seti henuz test
edilmedi - ama Faz 1'e gecerken bu feature'larin onceligini artiran dogru,
raporlanabilir bir negatif sonuc.

FAZ 0 KAPISI (PROJECT_SPEC.md bolum 6): "a skill table exists comparing model
vs all baselines, and the leakage audit passes" -> YAPISAL OLARAK KARSILANDI
(tablo var, 9/10 leakage testi geciyor, kalan 1 Faz 3'u dogru sekilde bekliyor).
ICERIK sorusu ("Tier 2 skill'i yeniyor mu") -> HAYIR, beklendigi gibi.

sure: ~1.5 sa (plan + kod + UC gercek hata bulundu ve duzeltildi)
surpriz: T8'i yazarken UC ayri, gercek hata bulundu, hicbiri "calisti" sanip
  gecmedim:
  (1) T6'nin climatology_forecast() SINIFLANDIRMA hedefi (spi_3) icin SUREKLI
      SPI ortalamasi donduruyordu (araligi [-0.029,0.044], sifir civarinda) -
      Brier/BSS hesaplamak icin KULLANILAMAZ (olasilik degil). T6 tekrar acildi
      (kullanicinin onayiyla, dosya src/models/baselines.py'a - mimari ayrim
      korunarak): probability_climatology_forecast() vb dort yeni fonksiyon
      eklendi, referans donemindeki AMPIRIK altina-dusme oranini hesapliyor.
      Kendiliginden gelen dogrulama: bu oran havza genelinde 0.1597 cikti,
      teorik Phi(-1)=0.1587'den sadece +0.0010 sapiyor - SPI fit kalitesinin
      bagimsiz, beklenmedik bir dogrulamasi.
  (2) KRITIK: predictions.parquet (T7) "date" kolonunu ISSUE tarihi olarak
      kullaniyor (actual = target[t+lead]), baselines_monthly.parquet (T6) ise
      DOGRULAMA tarihi olarak (actual = target[t], persistence geriye bakiyor).
      Ikisini ayni "date" filtresiyle kiyaslamak SESSIZCE yanlis tarihleri
      esletiriyordu. Kanit: pred'in tarihini +lead kaydirinca base ile 45/45
      BIREBIR esitlendi (once 3/48). Kalici bir assert eklendi: iki kaynagin
      "actual" degerleri ortak tarihlerde HER ZAMAN birebir esit olmali, aksi
      halde T8 durur. Bu calistirmada headline sayilar DEGISMEDI (T7'nin kendi
      panel-sinir kirpmasi tesaduf eseri ayni 45 (hucre,ay) kumesini
      koruyordu) ama duzeltme YAPISAL, sansa dayanmiyor artik.
  (3) Duzeltme SIRASINDA bir sorun daha cikti: baseline'lar modelin HIC tahmin
      uretmedigi 3 ekstra ayi (test'in ilk lead-ay'lari) da hesaba katiyordu -
      adil olmayan bir kiyas. base artik SADECE pred'in kapsadigi tarihlere
      kisitlaniyor; duzeltme sonrasi n_dates model=baseline birebir esit oldu.
  (4) R² son derece negatif cikti (-4.6 ile -9.6 arasi) - manuel hesapla
      sklearn'e karsi dogrulandi (birebir eslesme), bug degil: PROJECT_SPEC
      4.4'un istedigi UZAMSAL (tarih-ici, hucreler arasi) R² tanimi, alisilan
      ZAMANSAL R²'den cok daha cezalandirici, cunku SPI'nin tek bir ayda
      hucreler arasi yayilimi dar (std~0.2-0.5). Tabloya aciklama notu eklendi.
acik varsayim: yok. Reliability diagram, spatially blocked CV, permutation
  testi B listesinde/Faz 3'te kaliyor.
sonraki: /leakage-audit (skeptic agent - CLAUDE.md'nin "Definition of done"
  bunu bir modelleme degisikligi icin zorunlu kiliyor), sonra /phase-gate

---

### T8 ek: iki dogrulama + bir spec boslugu (T8 kapandiktan sonra istendi)

**(A) Bug 2'nin "tesadufen ayni sayi" iddiasi - artik iddia degil, olculdu.**

Yontem: duzeltme oncesi ve sonrasi secimi yeniden kurup, uretilen satir
sayisini VE (cell_id, issue_date) INSTANCE KUMELERINI karsilastirdim; "sayilar
ayni cikti" tek basina dogrulama sayilmaz.

```
spi_3 (lead=3)  model satir: once=126,900  sonra=126,900   fark=0
                instance kumesi ozdes: True (yalniz-once=0, yalniz-sonra=0)
spi_1 (lead=1)  model satir: once=132,540  sonra=132,540   fark=0
                instance kumesi ozdes: True (yalniz-once=0, yalniz-sonra=0)
```

MEKANIZMA (tek cumle): T7'nin kendi `y_all.notna()` kirpmasi issue tarihlerini
zaten panel_sonu - lead'de bitirdigi icin (spi_3: 2025-09, spi_1: 2025-11),
kaydirilmis tarihler tam olarak 2025-12'ye oturur ve test bolunmesinin ilk
issue tarihi 2022-01 kaydirildiginda hala pencerenin icinde kalir - yani
[2022-01, 2025-12] filtresi her iki tarih konvansiyonunda da HICBIR satiri
kirpmaz, dolayisiyla kaydirma grup etiketlerinin bijeksiyonudur ve ayni 45/47
grup degerinin ortalamasi degismez. Bu yapisal bir sonuc (T7'nin panel-sinir
kirpmasinin turevi), sans degil - ama duzeltme olmadan ayni ozelligin gelecek
bir panel uzamasinda korunacaginin GARANTISI yok, o yuzden kalici assert sart.

**(B) Kayit duzeltmesi: "headline sayilar degismedi" yalnizca fix (2) icin dogru.**

Fix (3) - baseline'lari modelin tam tarih kumesine kisitlamak - spi_1'in
baseline sayilarini GERCEKTEN degistirdi (48 -> 47 tarih):

```
climatology         RMSE 0.7914875714124646 -> 0.7914596956807570   DEGISTI
persistence         RMSE 1.0163650886097528 -> 1.0278173790206566   DEGISTI
known_accumulation  RMSE 0.7914875714124646 -> 0.7914596956807570   DEGISTI
```

spi_3'te degismemesinin nedeni de olculdu, varsayilmadi: fazla 3 ay
(2022-01/02/03) icin `actual_prob` tum 1,823 hucrede TEK SINIF (hepsi 0.0) -
AUC tanimsiz oldugu icin bu aylar zaten dusuyordu. Yani spi_3'un sabit kalmasi
"degismedi" degil, "zaten hesaba girmiyordu".

**(C) Atlanan test adiyla dogrulandi.**

`tests/test_leakage.py::test_permutation_yields_no_skill` - tek atlanan test.
`pytest.importorskip("src.eval.permutation")` ile atliyor; `src/eval/` altinda
yalnizca `__init__.py` ve `skill.py` var, permutation modulu gercekten yok
(dosya sisteminden dogrulandi). PROJECT_SPEC 4.4 permutation testini Faz 3
robustness isi olarak listeliyor, yani atlanmasi plana uygun. Reliability
diagram ve spatially blocked CV HIC test degildi - skill tablosunun dipnotunda
Faz 3 isi olarak duruyorlar; "atlanan test" onlar degil.

**(D) SPEC BOSLUGU - PROJECT_SPEC 7 bu senaryoyu kapsamiyor.**

7. Failure conditions yalnizca *Tier 2*'nin climatology'yi gecememesini
ongoruyor ve cevabi "Tier 1'e daral" olarak veriyor. Ama olculen sonuc
*Tier 1'in kendisinin de* (spi_1@+1, RMSE 0.886 vs climatology 0.791, skill
-0.120) climatology'yi gecemedigi. Bu durumda "Tier 1'e daral" bir cikis yolu
degil - daralacak yer kalmiyor. Ayrica 2.1 "Tier 1 should reach meaningful
skill" diyor; bu artik DOGRULANMAMIS bir varsayim, cunku Faz 0 onu test etti ve
gecemedi.

Bunu "beklenen sonuc" diye gecistirmek yanlis olur: spi_3@+3 icin negatif
sonuc PROJECT_SPEC'in kendi Problem 2'sinde ONCEDEN kayitliydi, spi_1@+1 icin
DEGILDI. Faz 0'in ozellikle minimal ozellik kumesi (MODIS NDVI/LST yok, derinlik
agirlikli toprak nemi anomalisi yok, SPEI yok) bunu tek basina Tier 1
aleyhine bir hukum yapmaz - ama spec'in bu ihtimali hic dusunmemis olmasi
gercek bir boslugu.

GEREKEN: Faz 1'e gecerken PROJECT_SPEC 7'ye dorduncu bir failure condition
eklenmeli ("Tier 1 tam ozellik kumesiyle de climatology'yi gecemezse" - cevabi
ne?), ve spi_1@+1 MODIS/SPEI/agirlikli toprak nemi eklendikten SONRA yeniden
test edilmeli. O test yapilana kadar 2.1'in Tier 1 iddiasi acik varsayim
olarak isaretlidir.

---

### T8 ikinci tur: skeptic audit'in 4 bulgusu duzeltildi, tablo yeniden uretildi

Skeptic'in 10 bulgusundan 4'u (kullaniciyla "duzeltmemiz lazim" olarak isaretlenen
kritik/major sinifindakiler) ele alindi. Digerleri (AUC'un mekansal anlami,
train/eval populasyon farki, known-accumulation'in ayirt edicilik gucu olmamasi,
test doneminin kuraklik tabanli oran farki) tasarim notu olarak kaldi, kod
degisikligi gerektirmiyor - skeptic'in kendisi de bunlari "minor/design" olarak
isaretlemisti.

**(1) skill.py - skill-score etiketi ters okunuyordu.** Aritmetik dogruydu
(`skill_score = 1 - model/baseline`, pozitif = model kazaniyor), ama tabloda
climatology satirinda "skill -0.120 (vs model)" olarak basiliyordu - okuyucu bunu
"climatology'nin modele karsi skoru" diye okur, oysa gercek anlami "modelin
climatology'ye karsi skoru". Duzeltme RENDER katmaninda: sutun basligi artik
"model skill (RMSE)" / "model BSS" - kimin skoru oldugu her satirda tek anlamli.
Anahtar isimleri de `skill_rmse_vs_model` -> `model_skill_rmse` olarak degisti.

**(2) baselines.py - persistence olasilik tahmini sert 0/1'den kalibre edilmis
gercek olasiliga cevrildi.** Referans donemde (1981-2016) havza-capinda tek bir
2-durumlu gecis tablosu (P(gelecek<esik | simdi<esik), P(gelecek<esik |
simdi>=esik)) olculup butun seriye uygulandi - climatology_forecast ile ayni
disipilin (fit_start/fit_end disinda hicbir veri kullanilmiyor).

**KRITIK - bu duzeltmenin kendisi bir sizinti icin iyi bir sizinti yaratti,
CLAUDE.md'nin "sonuc beklenenden iyi cikarsa once sizinti supheleni" kuralinin
tam da onlemeye calistigi durum:** ilk yazdigim versiyon, satirin KENDI tarihindeki
degeri "simdiki durum" olarak kullaniyordu. Ama baselines_monthly.parquet'te
"date" DOGRULAMA tarihi (T6/T8'in yerlesik sozlesmesi, bkz. skill.py'nin tarih-
kaydirma yorumu) - yani satirin kendi tarihindeki deger, tam olarak o satirin
CEVABI (`actual_prob`). Ilk calistirmada persistence'in AUC'u tam **1.0** cikti -
lead=3 icin imkansiz derecede iyi bir sonuc, hemen incelendi. Mekanizma: model
kendi cevabina bakiyordu. Duzeltme: uygulama adiminda `persistence_forecast()`
(zaten var olan, dogru kaydirilmis fonksiyon, `target[d-lead]`) kullanildi -
fit ile uygulamanin "simdi" tanimini ayni hale getirdi. Duzeltme sonrasi
persistence AUC = 0.483 (makul, rastgeleye yakin), sizinti kapandi. Bir de
build()'deki mode-tabanli saglamlik kontrolu ayni hatayi tasiyordu (actual_prob'a
gore gruplaniyordu, artik issue-time state'e gore duzeltildi).

Sonuc: spi_3@+3'un model_bss'i (modelin persistence'a karsi Brier Skill Score'u)
+0.377 (sert 0/1, YANLIS) -> -0.048 (kalibre, DOGRU). "Model persistence'i acikla
yeniyor" iddiasi tamamen ortadan kalkti - model kalibre edilmis persistence'i de
GECEMIYOR (persistence Brier 0.1958, model 0.2052).

**(3) build.py - modele lag-0 (esdeger, t anindaki) ozellikler eklendi.**
Skeptic'in bulgusu: model'in ozellikleri en yakin ay olarak t-1'i kullaniyordu,
oysa persistence baseline'i t anini (issue tarihini) kullaniyordu - model,
kendi baseline'ina karsi elini bir ay geriden basliyordu, spi_1@+1 aslinda +2
ay tahmini yapiyordu. `LAG_MONTHS = (0,1,2,3,6)` - lag=0, forecast anindaki
gozlemi (henuz gecmise kaymamis deger) temsil eder, hicbir hedefle ortusmuyor
(spi_3@+3: hedef [t+1,t+3], spi_3_lag0 [t-2,t] - bosluk var; spi_1@+1: hedef
t+1, spi_1_lag0 sadece t - bosluk var). `assert_no_future_reference()`'in genel
dongusu lag=0'i otomatik dogru kapsadi, kod degisikligi gerekmedi.

**(4) skill.py - iki gercek defect + bir eksiklik daha:**
  - Brier artik AUC ile ayni kosulda dusurulmuyor: tek-sinifli tarihlerde AUC
    tanimsiz ama Brier tanimli - eskiden ikisi birlikte dusuyordu, 10/45 tarihte
    (2 en genis kuraklik ayi dahil) Brier hic hesaplanmiyordu. Artik AUC n=35,
    Brier n=45 ayri sutunlar.
  - Eslestirilmis (paired) anlamlilik testi eklendi: her taban cizgisi icin
    model'in ve o taban cizgisinin tarih-bazli metrik serisi ayni tarihlerde
    eslesip paired t-test VE Wilcoxon signed-rank ile karsilastiriliyor (scipy,
    zaten requirements.txt'te bagimlilik olarak vardi, yeni paket eklenmedi).
    Bagimlilik varsayimi acikca ihlal ediliyor (ardisik SPI aylari otokorele) -
    tabloya ayri bir footnote ile "bu p-degerleri iyimser, resmi bir anlamlilik
    iddiasi degil" notu eklendi, gizlenmedi.

**YENIDEN URETILEN SONUCLAR (T6 -> T7 -> T8 sirayla rerun edildi, 9/10 leakage
testi hala geciyor, degisen tek sey lag-0 ozellik + kalibre persistence):**

spi_3@+3 (35/45 tarih AUC icin, 45/45 Brier icin): model AUC 0.4768, Brier
0.2052; climatology AUC 0.5129, Brier 0.1949 (model_bss -0.053, p=0.014/0.078);
persistence (kalibre) AUC 0.4826, Brier 0.1958 (model_bss -0.048, p=0.015/0.128).
Model artik HICBIR taban cizgisini (climatology DA persistence DE) acikca
gecmiyor - onceki "persistence'i aciyla yeniyoruz" basligi tamamen dustu.

spi_1@+1 (47 tarih): model MAE 0.7296, RMSE 0.8298 (onceki 0.7842/0.8861'den
IYILESTI - lag-0 ozelliginin dogrudan etkisi); climatology MAE 0.6988, RMSE
0.7915 (model_skill_rmse -0.048, onceki -0.120'den kuculdu ama hala negatif,
p=0.303/0.105 - istatistiksel olarak ayirt edilemez); persistence MAE 0.8904,
RMSE 1.0278 (model_skill_rmse +0.193, p=0.065/0.021 - model'in persistence'i
gecmesi t-test'te sinirda, Wilcoxon'da anlamli).

**GUNCELLENEN BASLIK:** Model, lag-0 ozelligiyle kismen iyilesti ve kalibre
persistence'i (spi_1'de) muhtemelen geciyor, ama climatology'yi (her iki
hedefte de) hala GECEMIYOR ve spi_3'te kalibre persistence'i de gecemiyor.
Negatif sonuc AYNI KALDI, sadece daha az abartili ve daha dogru olculdu -
tam olarak CLAUDE.md'nin istedigi: "beklenenden iyi cikan sonuc -> once
sizinti supheleni" kurali BIR SIZINTI YAKALADI (persistence AUC=1.0), ve
duzeltmeler sonucu degistirmedi, sadece daha durust olcculdu.

acik varsayim: p-degerlerinin bagimsizlik varsayimi ihlal ediliyor (dipnotta
belirtildi). Reliability diagram, spatially blocked CV, permutation testi
hala Faz 3'te.

sonraki: /leakage-audit'in bu ikinci turu (skeptic'in bulgularinin duzeltilmis
hali) gozden gecirilmeli mi, yoksa /phase-gate'e mi gecilmeli - kullaniciya
soruldu.

---

### T8 ucuncu tur: bagimsiz dogrulama + p-deger yonu duzeltmesi + SS7 boslugunun GUNCEL rakamlarla yeniden yazilmasi

**Bagimsiz (clean-room) dogrulama yapildi.** skill.py/baselines.py'nin kendi
kodunu hic cagirmadan, sadece parquet dosyalarindan + numpy/pandas/sklearn/scipy
ile sifirdan yeniden hesaplandi: tablodaki HER rakam (Brier, AUC, MAE, RMSE, R2,
model_bss, model_skill_rmse, 4 p-degeri) gosterilen hassasiyette birebir
eslesti. Ek kontroller: kalibre persistence oranlari (0.1695/0.1583) panelden
bagimsiz yeniden turetildi, ayni cikti; lag-0 ozelliklerinin panel sutunlariyla
shift(0) kimligi dogrulandi (5/5 sutun); training_summary.json'da 47 ozellikten
9'unun _lag0 oldugu ve modelin gercekten yeniden egitildigi (8.250 farkli tahmin
degeri - gercek bir surekli dagilim) teyit edildi; climatology_prob'un sadece 11
farkli deger almasi ilk bakista supheli gorundu ama 36 yillik referans donemde
"esik-alti yil sayisi/36" kesri oldugu icin dogasi geregi ayrik oldugu, ve
dagilimin k=1..11 araliginda SPI'nin teorik %15-19 oranina uygun bir tepe
civarinda oldugu dogrulandi - bug degil.

**Ancak bagimsiz dogrulama, IKINCI bir goz'un yerini TUTMUYOR** - ayni kisi hem
uretim kodunu hem dogrulama script'ini yazdigi icin ayni tasarim korlugunu
paylasabilir. Skeptic agent'in dar kapsamli (tam pipeline degil, bu turun diff'i
+ 4 bulgunun cozumu + yeni kod) ikinci turu ayri olarak calistirildi (asagida).

**p-deger sunum sirasi duzeltildi: Wilcoxon once, t-test sonra.** spi_3@+3 icin
t-test p=0.014, Wilcoxon p=0.078 - ayni karsilastirma icin farkli taraflarda.
Mekanizma: paired t-test'in standart hata formulu farklarin BAGIMSIZ oldugunu
varsayarak ornek varyansindan hesaplanir; pozitif oto-korelasyon altinda ortalama
farkin GERCEK varyansi bu formulun hesapladigindan daha buyuktur, yani t-test
kendi belirsizligini MEKANIK olarak kucuk gosterir ve gercekte olmasi
gerekenden daha kucuk bir p basar - bu yonlu, bilinen bir sapma, belirsiz bir
uyari degil. Wilcoxon sira-tabanli oldugu icin bu ozel mekanizmayi paylasmiyor
(bagimliliga tamamen bagisik degil, ama bu spesifik yon-sapmasi ona uygulanmiyor).
Tabloda artik "p (Wilcoxon / t-test §)" olarak, Wilcoxon ONCE basiliyor ve
footnote'ta bu yon acikca yazili: iki test anlasmazsa Wilcoxon'un sayisi esas
alinacak, t-test'inki tamamlayici/iyimser bir rakam olarak okunacak.

**SS7 (Failure Conditions) boslugu - ONCEKI turdan farkli, GUNCEL rakamlarla:**
Bu bulgu daha once (ikinci T8 turunden ONCE, eski model_skill_rmse=-0.120
rakamiyla) phase0_log.md'ye yazilmisti. Duzeltmeler (kalibre persistence +
lag-0 ozellikleri) spi_1@+1'in climatology'ye karsi marjini KUCULTTU:

  ONCEKI:  model_skill_rmse = -0.120, p-degeri hic olculmemisti
  SIMDIKI: model_skill_rmse = -0.048, p=0.105 (Wilcoxon) / 0.303 (t-test)

Sonuc nitelik olarak degisti: eskiden "model climatology'yi acikca kaybediyor"
denebilirdi (12 puanlik fark), simdi dogru ifade "model ile climatology
ISTATISTIKSEL OLARAK AYIRT EDILEMIYOR, nokta tahmini hafif climatology lehine
ama bu fark gurultu payinin icinde" - ki bu, PROJECT_SPEC 7'nin hic
ongormedigi bir UCUNCU durum: ne "Tier 1 acikca basarisiz" (spec'in kapsamadigi
orijinal boslugu), ne de "Tier 1 acikca basarili" (spec'in 2.1'deki varsayimi) -
"olculemeyecek kadar kucuk fark, daha fazla veri/ozellik gerekiyor" durumu.

Bu, boslugu KAPATMIYOR, INCELTIYOR: PROJECT_SPEC 7'ye eklenecek dorduncu kosul
hala gerekli, ama sart ifadesi "Tier 1 climatology'yi ACIKCA gecemezse" degil
"Tier 1 climatology'den ISTATISTIKSEL OLARAK AYRISMAZSA" olmali - cunku
"acikca basarisiz" ile "belirsiz" arasindaki fark, Faz 1'de MODIS/SPEI/agirlikli
toprak nemi eklendiginde neyin "basari" sayilacagini (ornegin p<0.05 ile
climatology'yi GECMEK mi, yoksa sadece nokta tahmininin pozitif olmasi mi)
onceden netlestirmeyi gerektiriyor - bu netlestirme simdi yapilmadi, Faz 1
baslamadan once ETRAFLICA yapilmasi gereken acik bir karar olarak birakiliyor.

GEREKEN (guncellenmis): Faz 1 oncesi (1) PROJECT_SPEC 7'ye "Tier 1 tam ozellik
kumesiyle climatology'den istatistiksel olarak ayrisamazsa" kosulu + agirlikli
skeptic-onayli bir p-esigi (0.05? Wilcoxon mu t-test mi esas alinacak - bu
konusmada Wilcoxon'un esas alinmasi karara baglandi, spec'e de yazilmali)
eklenmeli, (2) spi_1@+1 MODIS/SPEI/agirlikli toprak nemi eklendikten SONRA
AYNI paired-test protokolüyle yeniden olculmeli.

acik varsayim: hangi p-esigi/hangi test "basari/basarisizlik" karari icin esas
sayilacak, kullaniciyla henuz netlesmedi - Faz 1 baslamadan once cevaplanmali.
