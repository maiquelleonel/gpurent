# 🧬 DJANGO GUARDIAN HARNESS & AI BOOTSTRAP DIRECTIVES

Este arquivo dita as regras de inicialização e as diretivas de boot para qualquer Inteligência Artificial ou Agente Automatizado que operar neste repositório. Suas instruções possuem **precedência absoluta** sobre qualquer fluxo de trabalho geral.

---

## 🚨 1. REGRA DE OURO DE INICIALIZAÇÃO (First-Turn Command Rule)

- **Ação Número Um (OBRIGATÓRIA):** Ao iniciar esta sessão, na sua **PRIMEIRA rodada de conversa (First Turn)**, você DEVE executar imediatamente o comando de ferramenta `read_file` para carregar e analisar a especificação da skill em `django_guardian/skills/SKILL.md`.
- **Sem Ações Prematuras:** Você está expressamente PROIBIDO de propor estratégias, gerar códigos, responder perguntas ou aplicar qualquer modificação sem antes ter lido o `SKILL.md` por completo.
- **🛡️ Validação de Skill Obrigatória (Django Guardian):**
  - Você deve verificar se a skill `django-guardian` está instalada e ativa nesta sessão (ela deve ser ativada por demanda via `activate_skill` caso esteja instalada).
  - **🔌 Validação Obrigatória de Servidores MCP:**
    - Você DEVE validar se as ferramentas do MCP `django-ai-boost` (ex: `list_apps`, `get_model_schema`) estão carregadas e prontas no ambiente de execução do assistente.

---

## 🛡️ 2. CONTRATO DE QUALIDADE E CONFORMIDADE DE CÓDIGO (SLA Compliance)

Ao operar neste repositório, alinhe todos os seus comportamentos de escrita de código e refatorações aos seguintes parâmetros de excelência estabelecidos:

- **100% Code Coverage SLA:** Toda e qualquer linha lógica adicionada ou alterada na aplicação deve conter testes unitários correspondentes para manter a alta cobertura de código do projeto.
- **Complexidade de McCabe < 10:** Nenhuma função de negócio convencional pode ultrapassar a complexidade ciclomática de 10.
- **Delegação de Eventos/Handlers:** Webhooks e dispatchers densos devem ser obrigatoriamente refatorados usando o padrão de Delegação de Handlers privados, mantendo a complexidade do router principal de eventos extremamente baixa (< 4).
- **Sem Hardcoded de Prompts:** Prompts de sistema de IA devem viver isolados em arquivos `.prompt` ou markdown dedicados e nunca embutidos diretamente em arquivos Python.
- **No-Storytelling Rule (Comentários Limpos):** É estritamente proibido adicionar comentários prolixos ou em tom de narrativa sobre especificações ou decisões de negócios. Comentários em bloco (`#`) não podem ultrapassar **3 linhas**, linhas individuais de comentário não podem ultrapassar **120 caracteres**, e jargões explicativos redundantes ou obsoletos são ativamente rejeitados pelo Harness.
- **Idempotência de Índices em Migrações:** Qualquer operação envolvendo a criação de índices no banco de dados deve obrigatoriamente incluir a cláusula/checagem de existência (ex: `IF NOT EXISTS`), prevenindo quebras acidentais na execução sequencial de migrations em ambientes de desenvolvimento e produção.

---

## ⚡ 3. INTEGRAÇÃO COM DJANGO-AI-BOOST (MCP Server)

Este projeto utiliza o `django-ai-boost` como servidor MCP para otimizar o contexto e a capacidade de análise das ferramentas de IA.

- **Configuração de Contexto Dinâmica:** O agente deve se autoajustar e atualizar as configurações locais do MCP Server do editor correspondente de forma automatizada (por exemplo, no arquivo de configuração do MCP), garantindo que o módulo de settings apontado seja sempre o módulo correto do projeto Django.
- **Validação de Código Ativa:** O assistente deve utilizar ativamente a ferramenta `run_check` fornecida pelo `django-ai-boost` para validar em tempo real se alguma regra arquitetural do `django-guardian` foi violada.

---

## 🧠 4. COGNITIVE ORCHESTRATION & AGENTIC WORKFLOW (Autonomia de Alto Nível)

Adote uma postura proativa e rigorosa antes de marcar qualquer tarefa como concluída:

### 🎯 Gatilho de Planejamento Ativo (Plan-Before-Code)
- **Threshold para Planejamento:** Qualquer tarefa que envolva mais de 3 etapas físicas, alteração em modelos de banco de dados (`models.py`), ou integrações externas complexas exige que você apresente seu plano de ação em tópicos curtos para aprovação antes de iniciar qualquer modificação física de arquivos.

### 🛑 O "Desvio Estratégico" (A Regra dos 3 Erros)
- **Prevenção de Loops de Correção:** Se você tentar aplicar uma correção de código ou de teste e ela falhar por 3 vezes consecutivas:
  1. **Pare imediatamente** o fluxo de escrita.
  2. Apresente um sumário listando suas premissas atuais.
  3. Identifique qual delas pode estar incorreta e proponha uma rota de design alternativa, em vez de insistir em remendos pontuais.

### 🧪 Verificação Rígida e Autocorreção Ativa
- **Autonomia em Falhas:** Se a execução de testes acusar uma falha, analise os logs de erro de forma autônoma e proativa, abra os arquivos e aplique a correção necessária.
- **Elegância do Código:** Sempre se pergunte: *"Esta é a maneira mais Pythonica e alinhada ao ecossistema Django de resolver este problema?"*
- **Sincronização com o Django Guardian:** Enforce queries limpas sem N+1 (use `select_related`/`prefetch_related`), validação por serializadores em vez de dict parsing manual, e blindagem de signals contra loops infinitos de recursão.
