# data/problems.py

# Специализации врачей
SPECIALISTS = {
    "gp": "Врач общей практики",
    "therapist": "Терапевт",
    "surgeon": "Хирург",
    "orthopedist": "Ортопед-травматолог",
    "neurologist": "Невролог",
    "gastroenterologist": "Гастроэнтеролог",
    "nephrologist": "Нефролог",
    "oncologist": "Онколог",
    "dermatologist": "Дерматолог",
    "virologist": "Вирусолог",
    "cardiologist": "Кардиолог",
    "ophthalmologist": "Офтальмолог",
    "reproductologist": "Репродуктолог",
    "radiologist": "Врач визуальной диагностики",
}

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

# Все проблемы (65 штук)
PROBLEMS = {
    "rentgen": {
        "name": "🦴 Консультация по рентгену",
        "category": "trauma",
        "description": "Расшифровка рентгеновских снимков, консультация травматолога",
        "price": 500,
        "specialists": ["orthopedist", "radiologist"],
        "urgent": False
    },
    "trauma_general": {
        "name": "🩸 Травма",
        "category": "trauma",
        "description": "Ушибы, растяжения, подозрение на перелом",
        "price": 500,
        "specialists": ["orthopedist", "surgeon"],
        "urgent": False
    },
    "wounds": {
        "name": "🔪 Колотые и резаные раны",
        "category": "trauma",
        "description": "Обработка ран, оценка глубины повреждения",
        "price": 500,
        "specialists": ["gp", "surgeon"],
        "urgent": True
    },
    "postop": {
        "name": "🏥 Послеоперационный уход",
        "category": "trauma",
        "description": "Уход после операции, обработка швов, рекомендации",
        "price": 500,
        "specialists": ["gp", "surgeon"],
        "urgent": False
    },
    "analysis": {
        "name": "🔬 Консультация по анализам",
        "category": "internal",
        "description": "Расшифровка результатов анализов крови, мочи, биохимии",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "mri_ct": {
        "name": "🧠 Консультация по МРТ/КТ",
        "category": "internal",
        "description": "Расшифровка снимков МРТ и КТ",
        "price": 500,
        "specialists": ["orthopedist", "neurologist", "oncologist", "surgeon"],
        "urgent": False
    },
    "no_appetite": {
        "name": "🍽️ Отказ от еды",
        "category": "common_symptoms",
        "description": "Питомец отказывается от корма",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "diarrhea": {
        "name": "💩 Диарея",
        "category": "common_symptoms",
        "description": "Расстройство стула, жидкий кал",
        "price": 500,
        "specialists": ["gp", "therapist", "gastroenterologist"],
        "urgent": False
    },
    "vomiting": {
        "name": "🤢 Рвота",
        "category": "common_symptoms",
        "description": "Рвота, срыгивание",
        "price": 500,
        "specialists": ["gp", "therapist", "gastroenterologist"],
        "urgent": False
    },
    "lameness": {
        "name": "🚶 Хромота",
        "category": "trauma",
        "description": "Питомец хромает, не наступает на лапу",
        "price": 500,
        "specialists": ["orthopedist"],
        "urgent": False
    },
    "limb_dysfunction": {
        "name": "🦵 Дисфункция конечностей",
        "category": "trauma",
        "description": "Слабость в конечностях, отказ от опоры",
        "price": 500,
        "specialists": ["orthopedist", "neurologist"],
        "urgent": True
    },
    "urination_disorder": {
        "name": "🚽 Нарушение мочеиспускания",
        "category": "internal",
        "description": "Затруднённое или частое мочеиспускание",
        "price": 500,
        "specialists": ["gp", "therapist", "nephrologist"],
        "urgent": False
    },
    "checkup": {
        "name": "🏥 Диспансеризация",
        "category": "internal",
        "description": "Профилактический осмотр, оценка здоровья",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "lumps": {
        "name": "🎈 Опухоли и шишки",
        "category": "internal",
        "description": "Новообразования на коже и под кожей",
        "price": 500,
        "specialists": ["surgeon", "oncologist"],
        "urgent": False
    },
    "deworming": {
        "name": "💊 Дегельминтизация и вакцинация",
        "category": "dentistry",
        "description": "График прививок и обработок от паразитов",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "constipation": {
        "name": "🚽 Запор",
        "category": "common_symptoms",
        "description": "Отсутствие стула, затруднённая дефекация",
        "price": 500,
        "specialists": ["gp", "therapist", "gastroenterologist"],
        "urgent": False
    },
    "blood_urine": {
        "name": "🩸 Кровь в моче",
        "category": "internal",
        "description": "Гематурия, изменение цвета мочи",
        "price": 500,
        "specialists": ["gp", "therapist", "nephrologist"],
        "urgent": True
    },
    "blood_stool": {
        "name": "🩸 Кровь в кале",
        "category": "internal",
        "description": "Кровь в стуле, чёрный кал",
        "price": 500,
        "specialists": ["gp", "therapist", "gastroenterologist"],
        "urgent": True
    },
    "cough": {
        "name": "🫁 Кашель",
        "category": "common_symptoms",
        "description": "Сухой или влажный кашель",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "sneezing": {
        "name": "🤧 Чиханье",
        "category": "common_symptoms",
        "description": "Частое чихание, выделения из носа",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "nasal_discharge": {
        "name": "👃 Выделения из носа",
        "category": "common_symptoms",
        "description": "Прозрачные или гнойные выделения",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "eye_discharge": {
        "name": "👁️ Выделения из глаз",
        "category": "common_symptoms",
        "description": "Слезотечение, гнойные выделения",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "itching": {
        "name": "🐕 Зуд / покраснения на коже",
        "category": "common_symptoms",
        "description": "Зуд, высыпания, покраснения",
        "price": 500,
        "specialists": ["gp", "therapist", "dermatologist"],
        "urgent": False
    },
    "lethargy": {
        "name": "😴 Апатия",
        "category": "common_symptoms",
        "description": "Вялость, слабость, сонливость",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "sterilization": {
        "name": "✂️ Кастрация / стерилизация",
        "category": "reproduction",
        "description": "Подготовка и рекомендации по стерилизации",
        "price": 500,
        "specialists": ["gp", "surgeon"],
        "urgent": False
    },
    "dental_care": {
        "name": "🦷 Уход за зубами",
        "category": "dentistry",
        "description": "Чистка зубов, лечение дёсен",
        "price": 500,
        "specialists": ["gp", "therapist", "surgeon"],
        "urgent": False
    },
    "diet_change": {
        "name": "🍲 Перевести на другой корм",
        "category": "internal",
        "description": "Смена рациона, подбор корма",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "neurological": {
        "name": "🧠 Неврологические отклонения",
        "category": "internal",
        "description": "Шаткая походка, круговые движения, неестественное положение головы",
        "price": 500,
        "specialists": ["surgeon", "neurologist"],
        "urgent": True
    },
    "second_opinion": {
        "name": "🎯 Получить второе мнение",
        "category": "specialist",
        "description": "Консультация узкого специалиста",
        "price": 500,
        "specialists": ["surgeon", "orthopedist", "gastroenterologist", "therapist", "cardiologist", "radiologist", "ophthalmologist", "nephrologist", "oncologist", "virologist", "dermatologist"],
        "urgent": False
    },
    "what_analyses": {
        "name": "🔬 Какие анализы нужно сдать",
        "category": "internal",
        "description": "Рекомендации по диагностике",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "leukemia": {
        "name": "🦠 Лейкоз (вирусная лейкемия кошек)",
        "category": "infectious",
        "description": "Вирусная лейкемия кошек (FeLV)",
        "price": 500,
        "specialists": ["virologist"],
        "urgent": False
    },
    "immunodeficiency": {
        "name": "🦠 Иммунодефицит",
        "category": "infectious",
        "description": "Вирусный иммунодефицит кошек (FIV)",
        "price": 500,
        "specialists": ["virologist"],
        "urgent": False
    },
    "fip": {
        "name": "🦠 ФИП (вирусный перитонит кошек)",
        "category": "infectious",
        "description": "Коронавирусный перитонит кошек",
        "price": 500,
        "specialists": ["virologist"],
        "urgent": False
    },
    "panleukopenia": {
        "name": "🦠 Панлекопения (парвовирусная инфекция кошек)",
        "category": "infectious",
        "description": "Парвовирусная инфекция кошек",
        "price": 500,
        "specialists": ["gp", "therapist", "virologist"],
        "urgent": True
    },
    "respiratory_viral": {
        "name": "🦠 Респираторные вирусные болезни",
        "category": "infectious",
        "description": "Ринотрахеит, калицивироз",
        "price": 500,
        "specialists": ["gp", "therapist", "virologist"],
        "urgent": False
    },
    "respiratory_bacterial": {
        "name": "🦠 Бактериальные респираторные болезни",
        "category": "infectious",
        "description": "Хламидиоз, токсоплазмоз, микоплазмоз",
        "price": 500,
        "specialists": ["gp", "therapist", "virologist"],
        "urgent": False
    },
    "blood_diseases": {
        "name": "🩸 Болезни кроветворения",
        "category": "infectious",
        "description": "Гемоплазмоз, анаплазмоз, пироплазмоз",
        "price": 500,
        "specialists": ["gp", "therapist", "virologist"],
        "urgent": True
    },
    "specialist_consult": {
        "name": "🎯 Консультация у специалиста",
        "category": "specialist",
        "description": "Приём узкого специалиста",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "proper_nutrition": {
        "name": "🥗 Правильное питание",
        "category": "internal",
        "description": "Рекомендации по питанию без составления рациона",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "diet_plan": {
        "name": "📋 Составление рациона",
        "category": "internal",
        "description": "Индивидуальный план питания",
        "price": 500,
        "specialists": ["gastroenterologist"],
        "urgent": False
    },
    "pre_surgery": {
        "name": "🔪 Подготовка перед хирургическим вмешательством",
        "category": "trauma",
        "description": "Рекомендации перед операцией",
        "price": 500,
        "specialists": ["gp", "therapist", "surgeon"],
        "urgent": False
    },
    "eye_trauma": {
        "name": "👁️ Травмы глаз",
        "category": "trauma",
        "description": "Выпадение третьего века, покраснение, помутнение роговицы",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": True
    },
    "seizures": {
        "name": "⚡ Судороги / эпилептические припадки",
        "category": "emergency",
        "description": "Эпилептические припадки, судороги",
        "price": 500,
        "specialists": ["neurologist"],
        "urgent": True
    },
    "poisoning": {
        "name": "☠️ Отравление",
        "category": "emergency",
        "description": "Отравление ядами, лекарствами, растениями",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": True
    },
    "allergy": {
        "name": "🤧 Аллергические реакции",
        "category": "common_symptoms",
        "description": "Отёк морды, крапивница, анафилаксия",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": True
    },
    "foreign_body": {
        "name": "🦴 Инородное тело в ЖКТ или дыхательных путях",
        "category": "emergency",
        "description": "Подозрение на заглатывание инородного предмета",
        "price": 500,
        "specialists": ["surgeon"],
        "urgent": True
    },
    "dyspnea": {
        "name": "🌬️ Одышка / затруднённое дыхание",
        "category": "emergency",
        "description": "Затруднённое дыхание без кашля и чихания",
        "price": 500,
        "specialists": ["gp", "therapist", "cardiologist"],
        "urgent": True
    },
    "polydipsia": {
        "name": "💧 Полидипсия / полиурия",
        "category": "internal",
        "description": "Повышенная жажда и мочеотделение",
        "price": 500,
        "specialists": ["gp", "therapist", "nephrologist"],
        "urgent": False
    },
    "fur_problems": {
        "name": "🐾 Проблемы с шерстью",
        "category": "common_symptoms",
        "description": "Колтуны, алопеция, тусклость, жирность",
        "price": 500,
        "specialists": ["gp", "therapist", "dermatologist"],
        "urgent": False
    },
    "behavior": {
        "name": "😾 Поведенческие проблемы",
        "category": "common_symptoms",
        "description": "Агрессия, страхи, навязчивые движения",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "bites": {
        "name": "🐕 Укусы",
        "category": "emergency",
        "description": "Укусы других животных, насекомых, змей",
        "price": 500,
        "specialists": ["gp", "therapist", "surgeon"],
        "urgent": True
    },
    "burns": {
        "name": "🔥 Ожоги",
        "category": "emergency",
        "description": "Термические, химические, солнечные ожоги",
        "price": 500,
        "specialists": ["gp", "therapist", "surgeon"],
        "urgent": True
    },
    "collapse": {
        "name": "😵 Обморок / коллапс",
        "category": "emergency",
        "description": "Внезапная слабость, падение",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": True
    },
    "arthritis": {
        "name": "🦴 Артрит / остеоартроз",
        "category": "trauma",
        "description": "Трудности вставания, боль при движении",
        "price": 500,
        "specialists": ["orthopedist"],
        "urgent": False
    },
    "mastitis": {
        "name": "🤱 Мастит",
        "category": "reproduction",
        "description": "Воспаление молочных желёз",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "difficult_birth": {
        "name": "🤰 Затруднённые роды / патология беременности",
        "category": "reproduction",
        "description": "Осложнения беременности и родов",
        "price": 500,
        "specialists": ["reproductologist"],
        "urgent": True
    },
    "newborn_care": {
        "name": "🍼 Уход за новорождёнными",
        "category": "reproduction",
        "description": "Слабый приплод, гипотермия, отказ от молока",
        "price": 500,
        "specialists": ["reproductologist"],
        "urgent": True
    },
    "chipping": {
        "name": "🔖 Чипирование / регистрация микрочипа",
        "category": "dentistry",
        "description": "Установка микрочипа, регистрация",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "nail_clipping": {
        "name": "✂️ Стрижка когтей и чистка анальных желёз",
        "category": "dentistry",
        "description": "Гигиенические процедуры",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "emergency_help": {
        "name": "🚨 Экстренная помощь",
        "category": "emergency",
        "description": "Шок, кровотечение, остановка дыхания",
        "price": 500,
        "specialists": [],
        "urgent": True
    },
    "cardiology": {
        "name": "❤️ Кардиологическое обследование",
        "category": "internal",
        "description": "ЭхоКГ, ЭКГ, давление",
        "price": 500,
        "specialists": ["cardiologist"],
        "urgent": False
    },
    "endocrine": {
        "name": "🦠 Эндокринные заболевания",
        "category": "internal",
        "description": "Сахарный диабет, гипотиреоз, гиперкортицизм",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "dentistry_surgery": {
        "name": "🦷 Стоматология",
        "category": "dentistry",
        "description": "Профессиональная чистка зубов под седацией, удаление, шлифовка",
        "price": 500,
        "specialists": ["surgeon"],
        "urgent": False
    },
    "antibiotics": {
        "name": "💊 Подбор антибиотиков",
        "category": "internal",
        "description": "По чувствительности, с учётом резистентности",
        "price": 500,
        "specialists": ["gp", "therapist"],
        "urgent": False
    },
    "pain_assessment": {
        "name": "🩺 Оценка боли",
        "category": "internal",
        "description": "Хроническая, острая, нейропатическая боль",
        "price": 500,
        "specialists": ["gp", "therapist", "neurologist", "orthopedist", "oncologist"],
        "urgent": False
    },
}