# Como Adicionar Novos Módulos ao Assistente

O núcleo do projeto foi desenhado para crescer além de Finanças (ex.: Tarefas, Lembretes, Notas).

1. Crie uma pasta em `backend/modules/<nome_do_modulo>/`.
2. Implemente uma classe herdando de `AssistantModule` (`backend/core/module_base.py`):
   - `get_commands()` -> lista de `/comandos` do módulo
   - `handle_command()` -> execução dos comandos
   - `can_handle_text()` -> filtro rápido para texto livre
   - `handle_text()` -> processamento da mensagem
   - `handle_callback()` -> botões inline com prefixo `<nome_do_modulo>:<acao>:<payload>`
   - `get_api_router()` -> endpoints FastAPI opcionais
3. Registre o módulo no `router.register(meu_modulo)` em `backend/app.py`.

