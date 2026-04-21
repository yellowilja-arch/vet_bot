from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton



# Подпись кнопки главного меню — импортируется в handlers для сравнения текста

TEXT_BTN_OUR_DOCTORS = "📋 Наши врачи"
TEXT_BTN_CLIENT_INFO = "📚 Информация"

CLIENT_INSTRUCTION_TEXT = """✨ ПРИВЕТ! РАССКАЖУ, КАК ВСЁ РАБОТАЕТ.

👇 ВСЕГО 4 ШАГА:

1️⃣ ВЫБЕРИТЕ
   • Нужную тему из списка
   • Или конкретного врача (раздел «Наши врачи»)

2️⃣ ОПЛАТИТЕ
   • Произведите оплату

3️⃣ РАССКАЖИТЕ О ПИТОМЦЕ
   • Имя, вид, возраст, вес, порода
   • Хронические болезни, вакцинация

4️⃣ ОБЩАЙТЕСЬ
   • Врач ответит в этом чате
   • Можно отправлять фото и видео

━━━━━━━━━━━━━━━━━━━━━━

📌 НА ЗАМЕТКУ

• Время консультации не должно превышать 45 минут
• Если врача нет онлайн — ответим в течение 24 часов
• Всю историю можно посмотреть в «Мои консультации»
• При возникновении технических вопросов/сложностей нажмите «🆘 Помощь» — администратор ответит

⚠️ ВАЖНО

• Онлайн-консультация не заменяет полноценный визит в клинику
• При острых/срочных проблемах обратитесь в клинику очно
• Если вы не отвечаете длительное время, консультация закроется автоматически"""


def get_main_keyboard(category_labels: list[str], universal_label: str) -> ReplyKeyboardMarkup:
    """Главное меню: категории проблем, универсальная тема, врачи и сервис."""
    buttons: list[list[KeyboardButton]] = [[KeyboardButton(text=label)] for label in category_labels]
    buttons.append([KeyboardButton(text=universal_label)])
    buttons.append(
        [
            KeyboardButton(text=TEXT_BTN_OUR_DOCTORS),
            KeyboardButton(text="📋 Мои консультации"),
        ]
    )
    buttons.append(
        [
            KeyboardButton(text=TEXT_BTN_CLIENT_INFO),
            KeyboardButton(text="🆘 Помощь"),
        ]
    )
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_category_problems_keyboard(problem_button_labels: list[str]) -> ReplyKeyboardMarkup:
    """Список сценариев в категории + назад."""
    rows = [[KeyboardButton(text=name)] for name in problem_button_labels]
    rows.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)





def get_topic_pay_keyboard(spec_key: str) -> InlineKeyboardMarkup:

    """Оплата выбранной темы (spec_key — ключ специализации из БД)."""

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="💰 Оплатить консультацию",
                callback_data=f"pay_topic:{spec_key}",
            )
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_topics")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)





def get_problem_info_keyboard(problem_key: str):

    """Совместимость: для прямой записи / legacy; основной поток — get_topic_pay_keyboard."""

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="💰 Оплатить консультацию",

                    callback_data=f"pay_topic:{problem_key}",

                )

            ],

            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_topics")],

        ]

    )





def get_back_keyboard():

    """Клавиатура с кнопкой 'Назад'"""

    return ReplyKeyboardMarkup(

        keyboard=[[KeyboardButton(text="🔙 Назад")]],

        resize_keyboard=True,

    )





def get_confirm_payment_keyboard():

    """Клавиатура для подтверждения оплаты"""

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data="confirm_payment")],

            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_payment")],

        ]

    )





def get_species_keyboard():

    """Клавиатура для выбора вида животного"""

    return ReplyKeyboardMarkup(

        keyboard=[

            [KeyboardButton(text="🐕 Собака"), KeyboardButton(text="🐈 Кошка")],

            [KeyboardButton(text="🐇 Грызун"), KeyboardButton(text="🐦 Птица")],

            [KeyboardButton(text="📝 Другое"), KeyboardButton(text="❌ Отмена")],

        ],

        resize_keyboard=True,

    )





def get_condition_keyboard():

    """Клавиатура для выбора упитанности"""

    return ReplyKeyboardMarkup(

        keyboard=[

            [KeyboardButton(text="🟢 Худощавый"), KeyboardButton(text="🟢 Нормальный")],

            [KeyboardButton(text="🟡 Упитанный"), KeyboardButton(text="🔴 Ожирение")],

            [KeyboardButton(text="❌ Отмена")],

        ],

        resize_keyboard=True,

    )





def get_rating_keyboard(consultation_id, doctor_id):

    """Клавиатура для оценки врача"""

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(text="⭐ 1", callback_data=f"rate:{consultation_id}:{doctor_id}:1"),

                InlineKeyboardButton(text="⭐ 2", callback_data=f"rate:{consultation_id}:{doctor_id}:2"),

                InlineKeyboardButton(text="⭐ 3", callback_data=f"rate:{consultation_id}:{doctor_id}:3"),

                InlineKeyboardButton(text="⭐ 4", callback_data=f"rate:{consultation_id}:{doctor_id}:4"),

                InlineKeyboardButton(text="⭐ 5", callback_data=f"rate:{consultation_id}:{doctor_id}:5"),

            ],

            [InlineKeyboardButton(text="❌ Пропустить", callback_data="skip_rating")],

        ]

    )





def get_recent_illness_keyboard():

    """Болезни за последний месяц — быстрый ответ «не болел»."""

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [InlineKeyboardButton(text="✅ Нет, не болел", callback_data="no_recent_illness")],

        ]

    )


def get_vaccination_keyboard() -> InlineKeyboardMarkup:
    """Комплексная вакцинация — Да / Нет / Не знаю."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data="vac_yes"),
                InlineKeyboardButton(text="❌ Нет", callback_data="vac_no"),
                InlineKeyboardButton(text="❓ Не знаю", callback_data="vac_unknown"),
            ],
        ]
    )


def get_support_keyboard():

    """Клавиатура для поддержки"""

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [InlineKeyboardButton(text="📝 Написать администратору", callback_data="contact_admin")],

            [InlineKeyboardButton(text="📜 История переписки", callback_data="support_history")],

            [InlineKeyboardButton(text="📋 Мои консультации", callback_data="my_cons")],

        ]

    )





def get_waiting_keyboard():

    """Клавиатура для ожидания врача"""

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [InlineKeyboardButton(text="✅ Да, я готов ждать", callback_data="wait_accept")],

            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_topics")],

        ]

    )


def get_client_end_consultation_inline_keyboard(client_id: int) -> InlineKeyboardMarkup:
    """Напоминание 10 мин: клиент может завершить диалог с врачом."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Завершить консультацию",
                    callback_data=f"cli_end_cf:{client_id}",
                )
            ],
        ]
    )


def get_our_doctors_inline_keyboard(lines: list[tuple[int, str]]) -> InlineKeyboardMarkup:

    """lines: (telegram_id, текст на кнопке)"""

    rows = []

    for tid, label in lines:

        short = label if len(label) <= 58 else label[:55] + "…"

        rows.append([InlineKeyboardButton(text=short, callback_data=f"docsel:{tid}")])

    rows.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="doclist_close")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_topic_doctors_pick_keyboard(
    spec_key: str, lines: list[tuple[int, str]]
) -> InlineKeyboardMarkup:
    """Выбор врача после темы: lines — (telegram_id, подпись кнопки)."""
    rows = []
    for tid, label in lines:
        short = label if len(label) <= 58 else label[:55] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=short, callback_data=f"topicdoc:{tid}:{spec_key}"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_topics")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_doctor_free_pay_keyboard(doctor_id: int) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="💰 Оплатить консультацию",

                    callback_data=f"pay_direct:{doctor_id}",

                )

            ],

            [InlineKeyboardButton(text="🔙 К списку врачей", callback_data="doclist_reopen")],

        ]

    )





def get_doctor_busy_keyboard(doctor_id: int) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [InlineKeyboardButton(text="⏳ Ждать", callback_data=f"docbusy_wait:{doctor_id}")],

            [InlineKeyboardButton(text="🔄 Выбрать другого", callback_data="doclist_reopen")],

            [InlineKeyboardButton(text="📋 Общая очередь", callback_data="docbusy_queue")],

        ]

    )





def get_doctor_offline_keyboard(doctor_id: int) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="💰 Оплатить (ответ до 24 ч)",

                    callback_data=f"pay_direct_offline:{doctor_id}",

                )

            ],

            [InlineKeyboardButton(text="🔄 Выбрать другого", callback_data="doclist_reopen")],

            [InlineKeyboardButton(text="📋 Общая очередь", callback_data="docbusy_queue")],

        ]

    )


