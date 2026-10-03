import json

from dbgpt._private.config import Config
from dbgpt.core import (
    ChatPromptTemplate,
    HumanPromptTemplate,
    MessagesPlaceholder,
    SystemPromptTemplate,
)
from dbgpt_app.scene import AppScenePromptTemplateAdapter, ChatScene
from dbgpt_app.scene.chat_db.auto_execute.out_parser import DbChatOutputParser

CFG = Config()


_PROMPT_SCENE_DEFINE_EN = "You are a database expert. "
_PROMPT_SCENE_DEFINE_ZH = "你是一个数据库专家. "

_DEFAULT_TEMPLATE_EN = """
Please answer the user's question based on the database selected by the user and some \
of the available table structure definitions of the database.
Database name:
     {db_name}
Table structure definition:
     {table_info}

Governed metric and field semantics matched to the question:
     {metric_context}

Observed sample values (use these to ground categorical filters; samples are not
guaranteed to be exhaustive):
     {value_hints}

Constraint:
    1.Please understand the user's intention based on the user's question, and use the \
    given table structure definition to create a grammatically correct {dialect} sql. \
    For any question that asks for data, a count, an aggregate, a list, or a comparison, \
    always populate the sql field and let the database produce the answer; do not invent \
    a numeric result in direct_response. Use direct_response only for non-data conversation \
    or when the schema is genuinely insufficient. 
    2.Always limit the query to a maximum of {top_k} results unless the user specifies \
    in the question the specific number of rows of data he wishes to obtain.
    3.You can only use the tables provided in the table structure information to \
    generate sql. If you cannot generate sql based on the provided table structure, \
    please say: "The table structure information provided is not enough to generate \
    sql queries." It is prohibited to fabricate information at will.
    4.Please be careful not to mistake the relationship between tables and columns when\
     generating SQL.
    5.Please check the correctness of the SQL and ensure that the query performance is\
     optimized under correct conditions.
    5a.When a filter uses a categorical/status/flag column, prefer the observed values\
     above and do not guess the meaning of codes such as Y/N, 0/1, or F/T. If the\
     user's wording is ambiguous, ask for clarification instead of silently swapping\
     a code.
    6.When the chat history contains a previous query, preserve its database, \
    filters and dimensions for follow-up questions unless the user explicitly \
    changes them. Ask for clarification if a reference such as "that result" \
    cannot be resolved safely.
    7.Please choose the best one from the display methods given below for data \
    rendering, and put the type name into the name parameter value that returns \
    the required format. If you cannot find the most suitable one, use 'Table' as \
    the display method. , the available data display methods are as follows: \
    {display_type}
    
User Question:
    {user_input}
Please think step by step and respond according to the following JSON format:
    {response}
Ensure the response is correct json and can be parsed by Python json.loads.

"""

_DEFAULT_TEMPLATE_ZH = """
请根据用户选择的数据库和该库的部分可用表结构定义来回答用户问题.
数据库名:
    {db_name}
    表结构定义:
    {table_info}

与问题匹配的指标和字段语义定义:
    {metric_context}

从数据库抽取的示例值（用于校准枚举/状态字段；示例不保证穷尽）:
    {value_hints}

约束:
    1. 请根据用户问题理解用户意图，使用给出表结构定义\
    创建一个语法正确的{dialect} sql。凡是涉及数据、数量、聚合、列表或比较的问题，\
    必须填写 sql 字段并交给数据库计算，禁止在 direct_response 中臆造数值；只有非数据对话\
    或表结构确实不足时才使用 direct_response。
    2. 除非用户在问题中指定了他希望获得的具体数据行数，否则始终将查询限制为最多\
     {top_k} 个结果。
    3. 只能使用表结构信息中提供的表来生成 sql，如果无法根据提供的表结构中生成 sql ，\
    请说：“提供的表结构信息不足以生成 sql 查询。” 禁止随意捏造信息。
    4. 请注意生成SQL时不要弄错表和列的关系
    5. 请检查SQL的正确性，并保证正确的情况下优化查询性能
    5a. 对枚举、状态、标志位字段，优先使用上面的实际示例值，禁止臆测 Y/N、0/1、F/T 等编码含义；\
    如果用户表述无法唯一映射到编码，应先澄清而不是静默替换。
    6.如果历史对话中包含上一轮查询，后续问题应沿用上一轮的数据库、筛选条件和维度，\
    除非用户明确要求修改；如果“刚才的结果”等指代无法安全解析，应先请求澄清。
    7.请从如下给出的展示方式种选择最优的一种用以进行数据渲染，\
    将类型名称放入返回要求格式的name参数值中，如果找不到最合适的\
    则使用'Table'作为展示方式，可用数据展示方式如下: {display_type}
用户问题:
    {user_input}
请一步步思考并按照以下JSON格式回复：
      {response}
确保返回正确的json并且可以被Python json.loads方法解析.

"""

_DEFAULT_TEMPLATE = (
    _DEFAULT_TEMPLATE_EN if CFG.LANGUAGE == "en" else _DEFAULT_TEMPLATE_ZH
)

PROMPT_SCENE_DEFINE = (
    _PROMPT_SCENE_DEFINE_EN if CFG.LANGUAGE == "en" else _PROMPT_SCENE_DEFINE_ZH
)

RESPONSE_FORMAT_SIMPLE = {
    "thoughts": "thoughts summary to say to user",
    "direct_response": "If the context is sufficient to answer user, reply directly "
    "without sql",
    "sql": "SQL Query to run",
    "display_type": "Data display method",
}


# Temperature is a configuration hyperparameter that controls the randomness of
# language model output.
# A high temperature produces more unpredictable and creative results, while a low
# temperature produces more common and conservative output.
# For example, if you adjust the temperature to 0.5, the model will usually generate
# text that is more predictable and less creative than if you set the temperature to
# 1.0.
PROMPT_TEMPERATURE = 0.5

prompt = ChatPromptTemplate(
    messages=[
        SystemPromptTemplate.from_template(
            _DEFAULT_TEMPLATE,
            response_format=json.dumps(
                RESPONSE_FORMAT_SIMPLE, ensure_ascii=False, indent=4
            ),
        ),
        MessagesPlaceholder(variable_name="chat_history"),
        HumanPromptTemplate.from_template("{user_input}"),
    ]
)

prompt_adapter = AppScenePromptTemplateAdapter(
    prompt=prompt,
    template_scene=ChatScene.ChatWithDbExecute.value(),
    stream_out=True,
    output_parser=DbChatOutputParser(),
    temperature=PROMPT_TEMPERATURE,
)
CFG.prompt_template_registry.register(prompt_adapter, is_default=True)
