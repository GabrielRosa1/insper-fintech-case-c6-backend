## ⚠️ Sobre os dados (CSV grandes)

Os arquivos `.csv`, que fizeram parte da análise, da pasta `data/raw/` **não estão incluídos no repositório**.

Isso foi feito porque esses arquivos são muito grandes e não são adequados para versionamento com Git.

---

## 📥 Como obter os dados

Para gerar ou baixar os dados necessários, utilize os scripts disponíveis na pasta `scripts/`.

### Passo a passo:

1. Acesse a pasta de scripts:

   ```bash
   cd scripts
   ```

2. Execute o(s) script(s) de coleta/download:

   ```bash
   python nome_do_script.py
   ```
---

## 💡 Observação

Sempre que alguém clonar este repositório, será necessário rodar os scripts da pasta `scripts/` para reconstruir os dados locais.

---

## 🚀 Requisitos

Instale as dependências antes de rodar os scripts:

```bash
pip install -r requirements.txt
```

---