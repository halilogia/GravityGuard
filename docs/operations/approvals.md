# İşlem onayları (Approvals)

Bir kural bir işlemi reddettiğinde ajan o işlemi kendi başına açamaz. Ret cevabı bir **onay bileti**
bırakır; kararı yalnızca kullanıcı verir. Onay "bu kural kapandı" demek değildir: tek bir parmak izine
bağlıdır, süresi dolara ve o çağrıda tükenir.

## Akış

1. **Kural reddeder.** Cevabın sonunda bilet kimliği görünür:
   `Onay: kullanıcı yalnızca bu işlemi \`gravityguard approvals allow <id>\` ile açabilir`.
   Bilet `~/.gravityguard/approvals/pending/<id>.json` dosyasına yazılır.
2. **Kullanıcı inceler.** `gravityguard approvals list` bekleyen biletleri, `gravityguard approvals show <id>`
   hangi kuralın neyi engellediğini gösterir.
3. **Kullanıcı karar verir.** `gravityguard approvals allow <id>` engeli kaldırır; kimliğin elle yazılması
   istenir. `gravityguard approvals deny <id>` engeli korur. Panelde de aynı düğmeler var
   (`engine/approval_control.py`).
4. **Onay tükenir.** Varsayılan 30 dakika, en fazla 120 dakika; varsayılan 1 kullanım, en fazla 10
   (`--minutes`, `--uses`). Süre dolunca veya kullanım bitince engel kendiliğinden geri gelir.
   `gravityguard approvals revoke <id>` kullanılmamış onayı geri alır.

## Parmak izi

Bilet `sha256(kural + araç + tam argümanlar)` ile anahtarlanır. Yani `dispatcher.py` dosyasına yapılan
**her** düzenlemeyi değil, **o** düzenlemeyi onaylar. Argümanların kendisi diske yazılmaz; yalnızca
özetleri saklanır, dosya içerikleri `~/.gravityguard` altına düşmez.

Aynı işlem tekrar reddedilirse yeni bilet açılmaz; var olan biletin `seen` sayacı artar. Kullanıcı bir kez
karar verdikten sonra aynı parmak izi için tekrar sorulmaz.

## Ajan onay veremez

- `gravityguard approvals allow|deny|revoke`, `approval_control.py` ve
  `approvals.approve/reject/revoke(...)` çağrıları ajan kabuğunda `POLICY_INTEGRITY` ile reddedilir
  (`shell_rules.py`).
- Onay deposu (`~/.gravityguard/approvals/`) dosya araçlarına kapalıdır (`policy_integrity.py`).
- `allow` ve `revoke` komutları etkileşimli terminal ister; doğrulama kimliğin elle yazılmasıyla yapılır.

Bu, kanca düzeyinde bir korumadır, işletim sistemi izni değildir.

## Sınırlar

- `GUARD_UNAVAILABLE` (motor çöktü) onaya açılmaz: ortada bir politika kararı yoktur.
- Onay yalnızca `deny` / `block` kararlarını etkiler; `continue` (durma kapıları) ve `allow` değişmez.
- Duraklatma anahtarı (`gravityguard pause`) hâlâ zorunlu güvenlik tabanını açmaz; onay ise kullanıcının
  bilinçli, tek işlemlik kararıdır.
