# Mapa de Disponibilidade — MVP (PDF → mapa interativo)

Sistema que converte um **PDF vetorial de loteamento** (exportado de CAD) em um
**mapa interativo de disponibilidade** (HTML), com os lotes clicáveis e coloridos
por status. **100% determinístico — não usa IA.** Mesmo PDF + mesmos parâmetros =
mesma saída, sempre.

Tem **3 formas de usar**: site (página de upload), linha de comando e API.

## Instalação
Requer Python 3.9+.
```
pip install -r requirements.txt
```

## 1) Uso — site (página de upload)  ← mais fácil
```
uvicorn api:app --port 8000
```
Abra **http://localhost:8000** no navegador → escolha (ou arraste) um PDF → o mapa
aparece na tela. Dá para ajustar o **ângulo** na hora e **baixar o HTML** do mapa.

## 2) Uso — linha de comando
```
python pdf_to_map.py SEU_ARQUIVO.pdf -o mapa.html
```
Ajustando o ângulo e a faixa de área, e gerando PNG + GeoJSON:
```
python pdf_to_map.py SEU_ARQUIVO.pdf -o mapa.html --rotate -8 --snapshot mapa.png --geojson lotes.geojson
```
Status reais a partir de um CSV (colunas: index,status):
```
python pdf_to_map.py SEU_ARQUIVO.pdf -o mapa.html --status-csv exemplo_status.csv
```

## 3) Uso — API (para integrar em outro sistema)
```
uvicorn api:app --port 8000
curl -X POST "http://localhost:8000/converter?rotate=-8" -F "arquivo=@SEU_ARQUIVO.pdf" -o mapa.html
```

## Hospedagem gratuita para o MVP

O projeto pode ser publicado em um repositorio GitHub e executado gratuitamente
como um Docker Space no Hugging Face. O Space roda o FastAPI e o motor Python,
incluindo PyMuPDF, OpenCV, NumPy e Shapely. O arquivo `README_HF.md` ja contem a
configuracao esperada pelo Hugging Face.

Para separar a interface, o `index.html` pode ficar no Cloudflare Pages e o
Space funcionar como backend. Nesse modelo, o Pages hospeda a tela e encaminha
`/converter` e `/render` para a URL do Space. O processamento continua no
backend Python; o Pages sozinho nao executa essas bibliotecas nativas.

O ambiente gratuito do Hugging Face pode entrar em espera quando fica sem uso,
portanto o primeiro PDF depois de um periodo parado pode demorar mais para
começar. PDFs enviados e arquivos gerados devem ser tratados como temporarios.

## Parâmetros (CLI)
| Parâmetro | Padrão | O que faz |
|---|---|---|
| `pdf` | (obrigatório) | caminho do PDF de entrada |
| `-o, --out` | `mapa.html` | arquivo HTML de saída |
| `--rotate` | `auto` | `auto` ou ângulo em graus (ex.: `-8`) |
| `--area-min` | `800` | área mínima do lote (filtro) |
| `--area-max` | `9000` | área máxima do lote (filtro) |
| `--max-px` | `2000` | resolução do lado maior (px) |
| `--page` | `0` | índice da página do PDF |
| `--status-csv` | — | CSV (`index,status`) com status reais |
| `--geojson` | — | exporta a geometria dos lotes em GeoJSON |
| `--snapshot` | — | exporta um PNG do resultado |
| `--title` | `Mapa de Disponibilidade` | título exibido no mapa |

## Como funciona (4 passos, sem IA)
1. **Lê os traços** do PDF (PyMuPDF) e **reconstrói os polígonos** dos lotes a
   partir da malha de linhas (shapely).
2. **Detecta a rotação** e endireita; **recorta** na área dos lotes (some a folha
   branca do CAD).
3. **Renderiza o fundo** (Pillow) e desenha os lotes como **SVG clicável**.
4. **Empacota tudo** num único HTML.

## Limitações e dicas
- **Rotação:** a autodetecção é uma *estimativa*. Loteamentos "orgânicos" (ruas
  curvas) podem precisar de ajuste manual com `--rotate N` (no site, use o campo
  "Ângulo").
- **Cobertura:** alguns CADs guardam certas quadras como **blocos reaproveitados**
  (XObjects), que o PDF não expõe como lotes individuais. Para **100% de cobertura
  e números de lote confiáveis, use o arquivo DXF/DWG** original.
- **Status:** sem `--status-csv`, o programa usa cores de **demonstração**.

## Arquivos do projeto
- `index.html` — a página do site (upload + visualização)
- `api.py` — servidor do site + API (FastAPI)
- `pdf_to_map.py` — motor de conversão + linha de comando
- `requirements.txt` — dependências
- `exemplo_status.csv` — exemplo de CSV de status
- `exemplo_Aquiraz_SetorE.html` / `.png` — exemplo já gerado
