# 🛡️ GravityGuard - AGENTS.md

Bu repo (GravityGuard) anayasal yapay zeka denetçisi ve bağlam koruma platformudur. Tüm ajanlar (Antigravity, Claude Code, Codex) burada çalışırken şu kurallara tabidir:

1. **Progressive Disclosure:** 350+ satırlık büyük kaynak dosyalarında (`src/*.ts`) körlemesine tam okuma yerine önce `token-lens` veya `rtk read -m 40` ile imza haritası çıkarılır, ardından ilgili satır aralıkları incelenir. 0-350 satırlık kompakt dosyalar doğrudan okunabilir.
2. **Cerrahi Düzenleme:** Dosyaları baştan sona ezmek yasaktır. Yalnızca hedeflenen blokları cerrahi diff ile güncelle.
3. **Tek Akışlı Uygulayıcı:** Tek bir görev için birden fazla alt ajan açarak token kotasını tüketme; doğrudan ve sıralı ilerle.
4. **Test ve Kanıt:** Yapılan her değişiklikten sonra `npm test` çalıştır ve testlerin geçtiğini doğrula.
5. **Global Anayasa:** [C:\Users\Halil Emre\AGENTS.md](file:///C:/Users/Halil%20Emre/AGENTS.md) ilkeleri geçerlidir.
