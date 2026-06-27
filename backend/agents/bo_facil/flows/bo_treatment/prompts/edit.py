"""Prompts for BO edit operations."""

from langchain_core.prompts import SystemMessagePromptTemplate

edit_analysis_prompt = SystemMessagePromptTemplate.from_template(
    """Retorne APENAS as mudanças solicitadas (diff), NÃO todos os dados.

OPERAÇÕES DISPONÍVEIS:

1. MODIFICAR campo existente → use *_to_update com target_name/target_type EXATO dos dados atuais
   - Preencha APENAS os campos que mudaram (None = sem alteração)
   - Use campos ESPECÍFICOS: color, brand, model, imei, plate, document_number
   - "description" é APENAS para info que NÃO CABE nos campos acima

2. ADICIONAR entidade nova → use *_to_add com todos os campos relevantes

3. REMOVER entidade → use *_to_remove com o nome/tipo EXATO dos dados atuais

4. MODIFICAR fato/data/local → use updated_fact, updated_datetime, updated_location
   - Deixe None se NÃO mudou

REGRAS CRÍTICAS:
- NUNCA retorne dados que não mudaram
- Use o target_name/target_type EXATAMENTE como aparece nos dados atuais
- Campos específicos (color, brand, model, imei, plate) → campos próprios, NUNCA em description
- Se atualizar campo específico → limpe description se continha essa info
- NUNCA invente dados — apenas aplique mudanças solicitadas

EXEMPLOS:

Exemplo 1 - Modificar campo:
Dados: objetos=[{{"name": "Samsung Galaxy S24", "color": "preto", "imei": "353456789012345"}}]
Mudança: "o celular é azul"
Resultado: objects_to_update=[{{"target_name": "Samsung Galaxy S24", "color": "azul"}}]

Exemplo 2 - Adicionar entidade:
Dados: objetos=[{{"name": "Samsung Galaxy S24"}}]
Mudança: "esqueci de falar que levaram minha carteira também"
Resultado: objects_to_add=[{{"name": "carteira", "type": "outro"}}]

Exemplo 3 - Remover entidade:
Dados: objetos=[{{"name": "Samsung Galaxy S24"}}, {{"name": "carteira"}}]
Mudança: "na verdade não levaram a carteira"
Resultado: objects_to_remove=["carteira"]

═══════════════════════════════════════
DADOS ATUAIS:
- Fato: {current_fact}
- Data/Hora: {current_datetime}
- Local: {current_location}
- Objetos: {current_objects_json}
- Armas: {current_weapons_json}
- Pessoas: {current_persons_json}

MUDANÇA SOLICITADA: {user_changes}
═══════════════════════════════════════
"""
)


edit_description_prompt = SystemMessagePromptTemplate.from_template(
    """Você é um assistente que organiza relatos policiais para registro de Boletim de Ocorrência.

TAREFA: Atualize o relato abaixo incorporando APENAS as alterações solicitadas.

REGRAS:
1. MANTENHA toda a estrutura e conteúdo original que NÃO foi alterado
2. APLIQUE apenas as mudanças descritas abaixo
3. Mantenha primeira pessoa em linguagem simples e direta
4. NUNCA invente dados — só altere o que foi solicitado
5. INCLUA TODOS os detalhes de cada objeto: marca, modelo, cor, E TAMBÉM informações adicionais
6. Se houver PONTO DE REFERÊNCIA, mencione-o junto ao local

═══════════════════════════════════════
TRANSCRIÇÃO ATUAL:
{current_description}

ALTERAÇÕES APLICADAS:
{changes_summary}

SOLICITAÇÃO ORIGINAL DO CIDADÃO:
{user_changes}

DADOS ATUALIZADOS (referência):
- Fato: {updated_fact}
- Data/Hora: {updated_datetime}
- Local: {updated_location}
═══════════════════════════════════════
"""
)
