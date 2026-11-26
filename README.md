# TinyTroupe Playground

TinyTroupe ile persona deneyleri yapmak için Mac üzerinde çalışan yerel web arayüzü. Persona, senaryo, soru ve görselleri her çalıştırmada kendiniz belirlersiniz. Üç yöntem vardır: bağımsız görüşme, grup konuşması ve **Siteyi gez** (ajanlar gerçek bir web sitesini tarayıcıda gezer).

## Docker ile kurulum (önerilen)

Docker Desktop açıkken proje klasöründe:

```bash
docker compose up --build -d
```

Ardından tarayıcıda `http://127.0.0.1:8765/` adresini açın. `localhost:8765` çalışmaz: uygulama yalnız bu adresi kabul eder. Kapatmak için `docker compose down`.

- Uygulama (`8765`) ve tarayıcı ekranı (`6080`) Mac'te yalnız `127.0.0.1` üzerinde yayımlanır.
- Konteyner proje klasörünü bağlamaz. Kod değiştiyse `docker compose up --build -d` ile yeniden derleyin.
- Tarayıcı profili, VNC parola dosyası ve TinyTroupe logları konteynerin bellekteki `/tmp` alanında, her deneye ait geçici bir klasörde tutulur. Deney bittiğinde, iptal edildiğinde veya hata verdiğinde bu klasör ve deneyin bütün süreçleri silinir.

## CLIProxyAPI ve model

Bu sürüm bağlantı olarak Tailscale üzerindeki CLIProxyAPI `:8317/v1` adresini kabul eder (`http://100.x.x.x:8317/v1/`). Docker Desktop konteynerin dış bağlantılarını Mac üzerinden yaptığı için Tailscale adresine konteynerden de erişilir.

**Ayarlar** sekmesinde CLIProxyAPI adresini ve istemci anahtarını girin. Adres ve seçtiğiniz model bu tarayıcıda hatırlanır. İstemci anahtarı yönetim anahtarı değildir; tarayıcı depolamasına kaydedilmez. **Modelleri yükle**, kimlik doğrulamalı `/v1/models` isteği yapar. Modeli listeden seçtikten sonra deneyi başlatın. Persona, senaryo, görseller ve tarayıcı modunda sayfa metni ile ekran görüntüleri seçilen modele gönderilir.

Anahtarı her açılışta girmemek için macOS Anahtar Zinciri'ni kullanın. İlk seferde Mac terminalinde, bu klasörde:

```bash
python3 mac_keychain.py set
```

`security` komutu anahtarı etkileşimli olarak sorar; anahtar komut satırı argümanına girmez. Sonraki açılışlarda `docker compose up` yerine:

```bash
python3 mac_keychain.py start
```

Bu komut Docker uygulamasını başlatır, anahtarı Anahtar Zinciri'nden alıp yalnız `127.0.0.1:8765` üzerinden uygulamanın belleğine aktarır. Anahtar Docker imajına, Compose ortam değişkenlerine veya tarayıcı depolamasına yazılmaz. Uygulama kapanınca bellekteki kopya kaybolur. Ayarlar sekmesinden bellekteki kopyayı silebilirsiniz; Anahtar Zinciri kaydını silmek için `python3 mac_keychain.py forget` kullanın. Anahtar Zinciri olmadan, anahtarı Ayarlar sekmesinde açık sayfa için elle girebilirsiniz.

**Yerel güvenlik sınırı:** Uygulama tek kullanıcılı bir yerel araçtır. Mac üzerinde çalışan başka bir yerel süreç `127.0.0.1:8765` arayüzüne erişebiliyorsa yüklü anahtarla model isteği başlatabilir; API anahtarının kendisini okuyamaz. Paylaşılan veya güvenilmeyen bir Mac'te uygulamayı açık bırakmayın ve işiniz bitince `docker compose down` çalıştırın.

Sonuçları ekranda izleyip Markdown olarak indirebilirsiniz. Deney girdileri otomatik kaydedilmez; indirilen rapora anahtar konmaz. Model listesinde görünmek, bir modelin TinyTroupe yapılandırılmış yanıtları ve görsel çağrılarıyla çalışacağını garanti etmez. Sentetik yanıtlar gerçek kullanıcı görüşmesi değildir.

## Siteyi gez: tarayıcı deneyi

Bu yöntem yalnız Docker kurulumunda çalışır.

1. **Hedef adres** alanına sitenin adresini girin:
   - Mac'te çalışan yerel bir site için Mac'te kullandığınız adresin aynısını yazın, örneğin `http://app.localhost:3000/`. Konteynerdeki tarayıcı `localhost` ve `*.localhost` adreslerini Mac'in yayımladığı portlara yönlendirir; adres, çerezler ve Host başlığı değişmez.
   - `http://` yalnız `localhost` ve `*.localhost` için kabul edilir. Diğer siteler `https://` olmalıdır.
   - `127.0.0.1` ve `::1` reddedilir; konteyner içinde bu adresler Mac'i değil konteynerin kendisini gösterir. Bunların yerine `localhost` yazın.
2. Deneyi başlatın. Sonuçlar bölümünde **Tarayıcı ekranını aç** bağlantısı çıkar. Bu bağlantı noVNC'yi yeni sekmede açar; deneye özel parola bağlantının `#` kısmındadır ve deney bitince geçersiz olur.
3. Açılan tarayıcıda siteye kendiniz giriş yapın, sonra uygulama sekmesine dönüp **Girişi tamamladım**'a basın. 15 dakika içinde devam edilmezse deney durur.
4. Devam ettiğinizde diğer sekmeler kapatılır, koruma kuralları kurulur ve ilk sekme hedef adrese yeniden açılır. Personalar bu oturumu sırayla kullanır. Gezintiyi aynı bağlantıdan (**Ajanları izle**) izleyebilirsiniz.

**Salt-okuma koruması (varsayılan) en iyi çabadır:**
- GET/HEAD/OPTIONS dışındaki istekler ve WebSocket bağlantıları engellenir. Service worker'lar bütün oturum boyunca kapalıdır.
- Sayfa geçişleri hedef host içinde kalır. Bir yönlendirme siteden çıkarırsa sayfa modele gönderilmeden önce hedef adrese geri dönülür.
- GET ile veri değiştiren uçlar engellenemez. POST ile okuma yapan sayfalar (ör. GraphQL) bu modda bozulabilir.

**Veri değiştiren isteklere izin ver** seçilirse ajanlar gerçek veriyi değiştirebilir ve bir personanın yaptığı değişiklik sonrakilere kalır. Sayfa geçişleri bu modda da hedef host'ta kalır.

Canlı bir sitede sayfa metni ve ekran görüntüleri CLIProxyAPI üzerinden model sağlayıcısına gider. Canlı ortamda ayrı bir test hesabı kullanın.

## Sorun giderme

- **Sayfa 403 veriyor:** `localhost:8765` yerine `http://127.0.0.1:8765/` adresini kullanın.
- **noVNC "password check failed" diyor veya bağlanmıyor:** Bağlantıyı bu deneyin sonuç kutusundan yeniden açın. Eski bir sekmenin parolası yeni deneyde geçmez. noVNC'yi de `localhost:6080` üzerinden değil, bağlantıdaki `127.0.0.1:6080` adresiyle açın.
- **Parolayı yapıştırmak:** noVNC'nin sol panelindeki pano alanına yapıştırıp uzak tarayıcıda `Ctrl+V` kullanın. VNC panosu yalnız Latin-1 taşır: ASCII parolalar sorunsuz geçer, `ş`, `ğ`, `ı` gibi Türkçe karakterler bozulur. Türkçe karakterleri klavyeyle yazın.
- **Yerel site açılmıyor:** Siteyi önce Mac'te aynı adresle açıp çalıştığını doğrulayın. Konteyner, Mac'te dinlenen porta `host.docker.internal` üzerinden gider.
- **Tarayıcı ajanlar düşünürken donuk görünüyor:** Koruma kuralları yalnız ajan bir tarayıcı işlemi yaparken çalışır. Model yanıtı beklenirken arka plandaki istekler bekler; bu beklenen davranıştır.
- **Model hatası:** Model listesinde olup TinyTroupe biçimine uymayan modeller hata verebilir; başka bir model deneyin.

## Docker'sız yerel kurulum

Görüşme ve grup yöntemleri Docker'sız da çalışır. Python 3.12 ile proje klasöründe:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -c constraints.txt
python3 start.py
```

Uygulama `127.0.0.1` üzerinde rastgele bir portta açılır. `python3 start.py --notebook` eski Jupyter arayüzünü açar; bunun için ayrıca `.venv/bin/python -m pip install jupyterlab` gerekir.

## Geliştirme

```bash
.venv/bin/python -m unittest test_web_app.py
docker compose run --rm -T --workdir /tmp playground python -m unittest discover -s /app -p test_web_app.py
```

TinyTroupe, `requirements.txt` içinde `v0.7.0` commit'ine sabitlenmiştir; PyPI'deki `tinytroupe` paketi bir yer tutucudur. Yeni bir TinyTroupe sürümüne geçmek için commit adresini ve `constraints.txt` dosyasını güncelleyin, testleri ve üç yöntemi yeniden çalıştırın.
