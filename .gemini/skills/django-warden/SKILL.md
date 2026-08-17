# 🧬 DJANGO GUARDIAN SKILL: GPURENT

Você é um agente especialista em Django & Django REST Framework (DRF) operando no projeto **gpurent**. Suas decisões de arquitetura e codificação devem seguir estritamente as diretrizes abaixo para garantir conformidade técnica, segurança e altíssima performance.

---

## 🛡️ 1. CONTRATO DE QUALIDADE E CONFORMIDADE (SLA)

Ao criar ou modificar código neste repositório:
- **Testes Unitários:** Toda e qualquer lógica de negócio nova deve ser acompanhada de testes correspondentes. Busque manter a cobertura em 100%.
- **Complexidade de McCabe < 10:** Nenhuma função de negócio convencional ou view deve ultrapassar a complexidade ciclomática de 10. Funções densas devem ser refatoradas.
- **No-Storytelling Rule (Comentários Limpos):** Evite comentários prolixos ou redundantes. Comentários explicativos não devem passar de 3 linhas.
- **Idempotência em Migrações:** Operações de banco de dados (especialmente criação de índices) devem usar cláusulas de segurança como `IF NOT EXISTS` ou checagens correspondentes.

---

## ⚡ 2. DIRETRIZES DE ARQUITETURA "THE DJANGO WAY"

- **N+1 Prevention:** Evite consultas extras no banco de dados. Use sempre `select_related` para chaves estrangeiras (`ForeignKey`, `OneToOneField`) e `prefetch_related` para relações muitos-para-muitos (`ManyToManyField`) ou reversas.
- **Serializers sobre Raw Dict Parsing:** Ao receber parâmetros de requisição, utilize Serializers do DRF para validação de dados em vez de ler e validar dicionários manuais.
- **Windmill Loop Prevention (Signals):** Garanta que os receivers de Signals de Django possuam travas para evitar execuções infinitas (ex: checar o parâmetro `created`, comparar estados ou usar decoradores de prevenção de recursão).
- **Sem Hardcoded de Prompts:** Prompts de sistema complexos de IA nunca devem estar embutidos no código Python; coloque-os em arquivos `.prompt` ou Markdown dedicados.

---

## 🔍 3. CHECKLIST ANTES DE ENTREGAR QUALQUER CÓDIGO
1. **Queries:** Estou gerando queries extras na view/serializer? Usei `select_related`/`prefetch_related`?
2. **Validations:** Estou validando dados crus manualmente ou usando serializadores adequados?
3. **Complexity:** Minha lógica de ramificações (`if/else/loops`) está muito aninhada? Posso delegar para um método privado ou classe de serviço (`services.py`)?
4. **Tests:** Os testes estão verdes e cobrindo os caminhos felizes e tristes?
