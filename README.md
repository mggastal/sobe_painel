# Painel Sobé

Visão gerencial de todos os dashs Sobé em uma página: https://mggastal.github.io/sobe_painel/

- `clientes.json`: cadastro (quem aparece, status ativo/pausado/arquivado, links extras). É editado pela aba **Admin** do painel.
- `coletar.py`: lê, **somente leitura**, o `data.json` publicado de cada dash e o status da última GitHub Action, e grava `status.json`. Não altera nada nos repos dos clientes.
- `.github/workflows/coletar.yml`: roda a coleta toda hora (:40) ou na hora, pelo botão "Salvar para todos" do Admin.
- Os lançamentos (`formato: resumo`) são lidos ao vivo pelo navegador direto do dash.

Formatos aceitos: `template` (perpétuo/captação), `resumo` (lançamentos), `embed` (dados dentro do HTML), `unibrasil`, `cidades`.
