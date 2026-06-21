# data_import — Clarius ölçümlerini TFT_Database.db'ye aktarma

`GUI_raw_data` veri tabanını **salt-okunur** açar. Bu yüzden ölçüm verisi
(Id-Vg / Id-Vd Excel'leri) önce `TFT_Database.db` içine yazılmalı. Bu klasör
o işi yapar.

## Kurulum (bir kez)

```bash
pip install -r data_import/requirements.txt
```

## 1) Boş veri tabanını oluştur

GUI'nin beklediği şemayla (Recipe → Wafer → Die → Subdie → Device → Experiment
→ Experimental_Detail, ayrıca Function_Config + Function_TFT_Transfer/Output)
boş bir DB üretir. Proje köküne `TFT_Database.db` yazar.

```bash
python data_import/create_tft_database.py            # mevcutsa hata verir
python data_import/create_tft_database.py --force    # üzerine yazar
```

## 2) Metadata'yı elle gir

`import_clarius_excel.py` içindeki `META` sözlüğünü düzenle (recipe / wafer /
die / subdie / device alanları). Kanal genişliği/uzunluğu dosya adındaki
`L<..>W<..>` deseninden otomatik okunur, istersen `META`'da elle ezebilirsin.
Aynı metadata ile tekrar çalıştırınca cihaz tekrar oluşturulmaz; deneyler aynı
cihaza eklenir.

İstersen metadata'yı bir JSON dosyasıyla da verebilirsin:

```bash
python data_import/import_clarius_excel.py FILE.xls --meta device_meta.json
```

## 3) Excel'i içe aktar

```bash
# önce sadece raporla (yazma yok):
python data_import/import_clarius_excel.py R2721-IdVg-...xls R889-IdVd-...xls --dry-run

# gerçek aktarım:
python data_import/import_clarius_excel.py R2721-IdVg-...xls R889-IdVd-...xls
```

Eşleme:

- **Id-Vg** dosyası: her "Run" sayfası, sabit Vds'te bir transfer taraması →
  her biri ayrı bir `TFT_Transfer` deneyi (kendi `drain_voltage_V` değeriyle).
- **Id-Vd** dosyası: tek sayfadaki çoklu Vgs blokları → tek bir `TFT_Output`
  deneyi (Vgs ailesi `gate_voltages_V` JSON listesinde). GUI bunu Vgs'ye göre
  ayrı eğrilere ayırarak çizer.

Sütun eşlemesi: `DrainI→i_ds_A`, `DrainV→v_ds_V`, `GateI→i_gs_A`, `GateV→v_gs_V`.

## 4) GUI'yi aç

```bash
python GUI_raw_data/run.py TFT_Database.db
```
veya yol vermeden çalıştırıp dosya seçiciden `TFT_Database.db`'yi seç.
