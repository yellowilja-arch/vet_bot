# data/problems.py

# Универсальная тема (нет в SPECIALIZATION_KEYS — в админке задаются только клинические роли)
UNIVERSAL_TOPIC_KEY = "universal_triage"

# Специализации: id → отображаемое название (эмодзи + роль). Без «ВОП» — только терапевт и узкие специалисты.
SPECIALISTS = {
    "therapist": "👨‍⚕️ Терапевт",
    "surgeon": "🔪 Хирург",
    "orthopedist": "🦴 Ортопед",
    "neurologist": "🧠 Невролог",
    "cardiologist": "❤️ Кардиолог",
    "oncologist": "🎗️ Онколог",
    "gastroenterologist": "🥣 Гастроэнтеролог",
    "nephrologist": "🩸 Нефролог",
    "dermatologist": "🐾 Дерматолог",
    "reproductologist": "🤰 Репродуктолог",
    "virologist": "🦠 Вирусолог",
    "radiologist": "📷 Врач визуальной диагностики",
    "ophthalmologist": "👁️ Офтальмолог",
    UNIVERSAL_TOPIC_KEY: "❓ Не знаю, куда обратиться",
}

# Порядок кнопок выбора специализации (админ / отображение списков) — 13 клинических ролей
SPECIALIZATION_KEYS = [
    "therapist",
    "surgeon",
    "orthopedist",
    "neurologist",
    "cardiologist",
    "oncologist",
    "gastroenterologist",
    "nephrologist",
    "dermatologist",
    "reproductologist",
    "virologist",
    "radiologist",
    "ophthalmologist",
]

# Категории
CATEGORIES = {
    "common_symptoms": {"name": "🩺 Общие симптомы", "emoji": "🩺"},
    "trauma": {"name": "🦴 Травмы и опорно-двигательный аппарат", "emoji": "🦴"},
    "internal": {"name": "❤️ Внутренние болезни", "emoji": "❤️"},
    "dentistry": {"name": "🦷 Стоматология и уход", "emoji": "🦷"},
    "infectious": {"name": "🐱 Инфекционные болезни", "emoji": "🐱"},
    "reproduction": {"name": "🤰 Репродуктология и неонатология", "emoji": "🤰"},
    "emergency": {"name": "🆘 Экстренная помощь", "emoji": "🆘"},
    "specialist": {"name": "🎯 Консультация специалиста", "emoji": "🎯"},
}

# Порядок категорий в главном меню клиента
CATEGORY_MENU_ORDER = [
    "common_symptoms",
    "trauma",
    "internal",
    "dentistry",
    "infectious",
    "reproduction",
    "emergency",
    "specialist",
]

# Все проблемы (65 штук)
PROBLEMS = {
    "rentgen": {
        "name": "🦴 Консультация по рентгену",
        "category": "trauma",
        "description": "Расшифровка рентгеновских снимков, консультация травматолога",
        "price": 1300,
        "specialists": ["orthopedist", "radiologist"],
        "urgent": False
    },
    "trauma_general": {
        "name": "🩸 Травма",
        "category": "trauma",
        "description": "Ушибы, растяжения, подозрение на перелом",
        "price": 1300,
        "specialists": ["orthopedist", "surgeon"],
        "urgent": False
    },
    "wounds": {
        "name": "🔪 Колотые и резаные раны",
        "category": "trauma",
        "description": "Обработка ран, оценка глубины повреждения",
        "price": 1300,
        "specialists": ["therapist", "surgeon"],
        "urgent": True
    },
    "postop": {
        "name": "🏥 Послеоперационный уход",
        "category": "trauma",
        "description": "Уход после операции, обработка швов, рекомендации",
        "price": 1300,
        "specialists": ["therapist", "surgeon"],
        "urgent": False
    },
    "analysis": {
        "name": "🔬 Консультация по анализам",
        "category": "internal",
        "description": "Расшифровка результатов анализов крови, мочи, биохимии",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "mri_ct": {
        "name": "🧠 Консультация по МРТ/КТ",
        "category": "internal",
        "description": "Расшифровка снимков МРТ и КТ",
        "price": 1300,
        "specialists": ["orthopedist", "neurologist", "oncologist", "surgeon"],
        "urgent": False
    },
    "no_appetite": {
        "name": "🍽️ Отказ от еды",
        "category": "common_symptoms",
        "description": "Питомец отказывается от корма",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "diarrhea": {
        "name": "💩 Диарея",
        "category": "common_symptoms",
        "description": "Расстройство стула, жидкий кал",
        "price": 1300,
        "specialists": ["therapist", "gastroenterologist"],
        "urgent": False
    },
    "vomiting": {
        "name": "🤢 Рвота",
        "category": "common_symptoms",
        "description": "Рвота, срыгивание",
        "price": 1300,
        "specialists": ["therapist", "gastroenterologist"],
        "urgent": False
    },
    "lameness": {
        "name": "🚶 Хромота",
        "category": "trauma",
        "description": "Питомец хромает, не наступает на лапу",
        "price": 1300,
        "specialists": ["orthopedist"],
        "urgent": False
    },
    "limb_dysfunction": {
        "name": "🦵 Дисфункция конечностей",
        "category": "trauma",
        "description": "Слабость в конечностях, отказ от опоры",
        "price": 1300,
        "specialists": ["orthopedist", "neurologist"],
        "urgent": True
    },
    "urination_disorder": {
        "name": "🚽 Нарушение мочеиспускания",
        "category": "internal",
        "description": "Затруднённое или частое мочеиспускание",
        "price": 1300,
        "specialists": ["therapist", "nephrologist"],
        "urgent": False
    },
    "checkup": {
        "name": "🏥 Диспансеризация",
        "category": "internal",
        "description": "Профилактический осмотр, оценка здоровья",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "lumps": {
        "name": "🎈 Опухоли и шишки",
        "category": "internal",
        "description": "Новообразования на коже и под кожей",
        "price": 1300,
        "specialists": ["surgeon", "oncologist"],
        "urgent": False
    },
    "deworming": {
        "name": "💊 Дегельминтизация и вакцинация",
        "category": "dentistry",
        "description": "График прививок и обработок от паразитов",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "constipation": {
        "name": "🚽 Запор",
        "category": "common_symptoms",
        "description": "Отсутствие стула, затруднённая дефекация",
        "price": 1300,
        "specialists": ["therapist", "gastroenterologist"],
        "urgent": False
    },
    "blood_urine": {
        "name": "🩸 Кровь в моче",
        "category": "internal",
        "description": "Гематурия, изменение цвета мочи",
        "price": 1300,
        "specialists": ["therapist", "nephrologist"],
        "urgent": True
    },
    "blood_stool": {
        "name": "🩸 Кровь в кале",
        "category": "internal",
        "description": "Кровь в стуле, чёрный кал",
        "price": 1300,
        "specialists": ["therapist", "gastroenterologist"],
        "urgent": True
    },
    "cough": {
        "name": "🫁 Кашель",
        "category": "common_symptoms",
        "description": "Сухой или влажный кашель",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "sneezing": {
        "name": "🤧 Чиханье",
        "category": "common_symptoms",
        "description": "Частое чихание, выделения из носа",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "nasal_discharge": {
        "name": "👃 Выделения из носа",
        "category": "common_symptoms",
        "description": "Прозрачные или гнойные выделения",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "eye_discharge": {
        "name": "👁️ Выделения из глаз",
        "category": "common_symptoms",
        "description": "Слезотечение, гнойные выделения",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "itching": {
        "name": "🐕 Зуд / покраснения на коже",
        "category": "common_symptoms",
        "description": "Зуд, высыпания, покраснения",
        "price": 1300,
        "specialists": ["therapist", "dermatologist"],
        "urgent": False
    },
    "lethargy": {
        "name": "😴 Апатия",
        "category": "common_symptoms",
        "description": "Вялость, слабость, сонливость",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "sterilization": {
        "name": "✂️ Кастрация / стерилизация",
        "category": "reproduction",
        "description": "Подготовка и рекомендации по стерилизации",
        "price": 1300,
        "specialists": ["therapist", "surgeon"],
        "urgent": False
    },
    "dental_care": {
        "name": "🦷 Уход за зубами",
        "category": "dentistry",
        "description": "Чистка зубов, лечение дёсен",
        "price": 1300,
        "specialists": ["therapist", "surgeon"],
        "urgent": False
    },
    "diet_change": {
        "name": "🍲 Перевести на другой корм",
        "category": "internal",
        "description": "Смена рациона, подбор корма",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "neurological": {
        "name": "🧠 Неврологические отклонения",
        "category": "internal",
        "description": "Шаткая походка, круговые движения, неестественное положение головы",
        "price": 1300,
        "specialists": ["surgeon", "neurologist"],
        "urgent": True
    },
    "second_opinion": {
        "name": "🎯 Получить второе мнение",
        "category": "specialist",
        "description": "Консультация узкого специалиста",
        "price": 1300,
        "specialists": [
            "surgeon",
            "orthopedist",
            "gastroenterologist",
            "therapist",
            "cardiologist",
            "radiologist",
            "ophthalmologist",
            "nephrologist",
            "oncologist",
            "virologist",
            "dermatologist",
        ],
        "urgent": False
    },
    "what_analyses": {
        "name": "🔬 Какие анализы нужно сдать",
        "category": "internal",
        "description": "Рекомендации по диагностике",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "leukemia": {
        "name": "🦠 Лейкоз (FeLV)",
        "category": "infectious",
        "description": "Вирусная лейкемия кошек (FeLV)",
        "price": 1300,
        "specialists": ["virologist"],
        "urgent": False
    },
    "immunodeficiency": {
        "name": "🦠 Иммунодефицит (FIV)",
        "category": "infectious",
        "description": "Вирусный иммунодефицит кошек (FIV)",
        "price": 1300,
        "specialists": ["virologist"],
        "urgent": False
    },
    "fip": {
        "name": "🦠 ФИП (перитонит кошек)",
        "category": "infectious",
        "description": "Коронавирусный перитонит кошек",
        "price": 1300,
        "specialists": ["virologist"],
        "urgent": False
    },
    "panleukopenia": {
        "name": "🦠 Панлейкопения",
        "category": "infectious",
        "description": "Парвовирусная инфекция кошек (панлейкопения)",
        "price": 1300,
        "specialists": ["therapist", "virologist"],
        "urgent": True
    },
    "respiratory_viral": {
        "name": "🦠 Респираторные вирусные",
        "category": "infectious",
        "description": "Ринотрахеит, калицивироз",
        "price": 1300,
        "specialists": ["therapist", "virologist"],
        "urgent": False
    },
    "respiratory_bacterial": {
        "name": "🦠 Бактериальные респираторные",
        "category": "infectious",
        "description": "Хламидиоз, токсоплазмоз, микоплазмоз",
        "price": 1300,
        "specialists": ["therapist", "virologist"],
        "urgent": False
    },
    "blood_diseases": {
        "name": "🩸 Болезни кроветворения",
        "category": "infectious",
        "description": "Гемоплазмоз, анаплазмоз, пироплазмоз",
        "price": 1300,
        "specialists": ["therapist", "virologist"],
        "urgent": True
    },
    "specialist_consult": {
        "name": "🎯 Консультация у специалиста",
        "category": "specialist",
        "description": "Приём узкого специалиста — маршрут по всем направлениям клиники",
        "price": 1300,
        "specialists": list(SPECIALIZATION_KEYS),
        "urgent": False
    },
    "proper_nutrition": {
        "name": "🥗 Правильное питание",
        "category": "internal",
        "description": "Рекомендации по питанию без составления рациона",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "diet_plan": {
        "name": "📋 Составление рациона",
        "category": "internal",
        "description": "Индивидуальный план питания",
        "price": 1300,
        "specialists": ["gastroenterologist"],
        "urgent": False
    },
    "pre_surgery": {
        "name": "🔪 Подготовка к операции",
        "category": "internal",
        "description": "Рекомендации перед операцией",
        "price": 1300,
        "specialists": ["therapist", "surgeon"],
        "urgent": False
    },
    "eye_trauma": {
        "name": "👁️ Травмы глаз",
        "category": "internal",
        "description": "Выпадение третьего века, покраснение, помутнение роговицы",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": True
    },
    "seizures": {
        "name": "⚡ Судороги / эпилепсия",
        "category": "internal",
        "description": "Эпилептические припадки, судороги",
        "price": 1300,
        "specialists": ["neurologist"],
        "urgent": True
    },
    "poisoning": {
        "name": "☠️ Отравление",
        "category": "internal",
        "description": "Отравление ядами, лекарствами, растениями",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": True
    },
    "allergy": {
        "name": "🤧 Аллергические реакции",
        "category": "common_symptoms",
        "description": "Отёк морды, крапивница, анафилаксия",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": True
    },
    "foreign_body": {
        "name": "🦴 Инородное тело",
        "category": "emergency",
        "description": "Подозрение на инородное тело в ЖКТ или дыхательных путях",
        "price": 1300,
        "specialists": ["surgeon"],
        "urgent": True
    },
    "dyspnea": {
        "name": "🌬️ Одышка / затруднённое дыхание",
        "category": "internal",
        "description": "Затруднённое дыхание без кашля и чихания",
        "price": 1300,
        "specialists": ["therapist", "cardiologist"],
        "urgent": True
    },
    "polydipsia": {
        "name": "💧 Полидипсия / полиурия",
        "category": "internal",
        "description": "Повышенная жажда и мочеотделение",
        "price": 1300,
        "specialists": ["therapist", "nephrologist"],
        "urgent": False
    },
    "fur_problems": {
        "name": "🐾 Проблемы с шерстью",
        "category": "common_symptoms",
        "description": "Колтуны, алопеция, тусклость, жирность",
        "price": 1300,
        "specialists": ["therapist", "dermatologist"],
        "urgent": False
    },
    "behavior": {
        "name": "😾 Поведенческие проблемы",
        "category": "common_symptoms",
        "description": "Агрессия, страхи, навязчивые движения",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "bites": {
        "name": "🐕 Укусы",
        "category": "trauma",
        "description": "Укусы других животных, насекомых, змей",
        "price": 1300,
        "specialists": ["therapist", "surgeon"],
        "urgent": True
    },
    "burns": {
        "name": "🔥 Ожоги",
        "category": "trauma",
        "description": "Термические, химические, солнечные ожоги",
        "price": 1300,
        "specialists": ["therapist", "surgeon"],
        "urgent": True
    },
    "collapse": {
        "name": "😵 Обморок / коллапс",
        "category": "internal",
        "description": "Внезапная слабость, падение",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": True
    },
    "arthritis": {
        "name": "🦴 Артрит / остеоартроз",
        "category": "trauma",
        "description": "Трудности вставания, боль при движении",
        "price": 1300,
        "specialists": ["orthopedist"],
        "urgent": False
    },
    "mastitis": {
        "name": "🤱 Мастит",
        "category": "internal",
        "description": "Воспаление молочных желёз",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "difficult_birth": {
        "name": "🤰 Затруднённые роды",
        "category": "reproduction",
        "description": "Осложнения беременности и родов",
        "price": 1300,
        "specialists": ["reproductologist"],
        "urgent": True
    },
    "newborn_care": {
        "name": "🍼 Уход за новорождёнными",
        "category": "reproduction",
        "description": "Слабый приплод, гипотермия, отказ от молока",
        "price": 1300,
        "specialists": ["reproductologist"],
        "urgent": True
    },
    "chipping": {
        "name": "🔖 Чипирование",
        "category": "dentistry",
        "description": "Установка микрочипа, регистрация",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "nail_clipping": {
        "name": "✂️ Стрижка когтей и чистка желёз",
        "category": "dentistry",
        "description": "Гигиенические процедуры, чистка анальных желёз",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "emergency_help": {
        "name": "🚨 Экстренная помощь",
        "category": "emergency",
        "description": "Срочная ситуация: после оплаты вы получите гайд первой помощи и адрес ближайшей клиники. При угрозе жизни звоните в клинику или везите питомца сразу.",
        "price": 1300,
        "specialists": [],
        "urgent": True
    },
    "cardiology": {
        "name": "❤️ Кардиологическое обследование",
        "category": "internal",
        "description": "ЭхоКГ, ЭКГ, давление",
        "price": 1300,
        "specialists": ["cardiologist"],
        "urgent": False
    },
    "endocrine": {
        "name": "🦠 Эндокринные заболевания",
        "category": "internal",
        "description": "Сахарный диабет, гипотиреоз, гиперкортицизм",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "dentistry_surgery": {
        "name": "🦷 Стоматология",
        "category": "dentistry",
        "description": "Профессиональная чистка под седацией, удаление, шлифовка",
        "price": 1300,
        "specialists": ["surgeon"],
        "urgent": False
    },
    "antibiotics": {
        "name": "💊 Подбор антибиотиков",
        "category": "internal",
        "description": "По чувствительности, с учётом резистентности",
        "price": 1300,
        "specialists": ["therapist"],
        "urgent": False
    },
    "pain_assessment": {
        "name": "🩺 Оценка боли",
        "category": "internal",
        "description": "Хроническая, острая, нейропатическая боль",
        "price": 1300,
        "specialists": ["therapist", "neurologist", "orthopedist", "oncologist"],
        "urgent": False
    },
    "direct_booking": {
        "name": "📋 Консультация с выбранным врачом",
        "category": "specialist",
        "description": "Запись к конкретному специалисту (раздел «Наши врачи»)",
        "price": 1300,
        "specialists": [],
        "urgent": False,
    },
    UNIVERSAL_TOPIC_KEY: {
        "name": "❓ Не знаю, куда обратиться",
        "category": "specialist",
        "description": "Общая консультация, подбор направления",
        "price": 1300,
        "specialists": [],
        "urgent": False,
    },
}