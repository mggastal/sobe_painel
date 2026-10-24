# Painel Sobé

Visão gerencial de todos os dashs Sobé em uma página: https://mggastal.github.io/sobe_painel/

- `clientes.json`: cadastro (quem aparece, status ativo/pausado/arquivado, links extras). Editado pela aba **Admin** do painel, que grava pelo servidor (`worker/`).
- `coletar.py`: lê, **somente leitura**, os dados já publicados de cada dash e o status da última GitHub Action, e grava `status.json` (série diária por plataforma, vendas Hotmart, impressões e cliques). Não altera nada nos repos dos clientes.
- `.github/workflows/coletar.yml`: roda a coleta toda hora (:40) ou na hora, pelo Admin.

Formatos aceitos em `clientes.json`: `template` (data.json dos dashs perpétuo/captação), `embed` (dados dentro do HTML; `pagina` escolhe o arquivo), `unibrasil`, `cidades`. `somar` junta outros repos no mesmo cliente (ex.: UniBrasil + PPGD).

## Servidor do Admin (Cloudflare Worker), uma vez só

1. GitHub → Settings → Developer settings → Fine-grained tokens → novo token, **só o repo sobe_painel**, permissões **Contents: Read and write** e **Actions: Read and write**.
2. Cloudflare → Workers & Pages → Create → Worker → nome **`sobepainel`** → Deploy → Edit code → cole `worker/painel-worker.js` → Deploy.
3. Worker → Settings → Variables and Secrets:
   - `GITHUB_TOKEN` (secret): o token do passo 1
   - `USUARIO_EQUIPE`: o mesmo do mapa mental
   - `SENHA_EQUIPE` (secret): a mesma do mapa mental
   - `REPO`: `mggastal/sobe_painel`
   - `ORIGENS`: `https://mggastal.github.io`
4. Abrir https://sobepainel.matheusgastal.workers.dev/ deve mostrar `GITHUB_TOKEN: definido` e `SENHA_EQUIPE: definida`.

Se o Worker tiver outro nome, troque `WORKER_URL` no topo do script de `index.html`.
