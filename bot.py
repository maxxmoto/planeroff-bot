import logging
import asyncio
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ---------- НАСТРОЙКИ ----------
BOT_TOKEN = "8857848759:AAEnrveFEeB-xBz8QZcdQhctMObi-YDHG1s"  # <-- токен от @BotFather

# Состояния диалога добавления задачи
TITLE, DEADLINE, WANT_REMINDER, REMINDER_TIME, CONFIRM = range(5)

# Хранилище задач (в памяти, только на время работы бота)
# tasks[user_id] = [ { "id": int, "title": str, "deadline": str|None,
#                     "remind_job": str|None } ]
tasks = {}

# Клавиатура главного меню
main_keyboard = ReplyKeyboardMarkup(
    [
        ["📋 Список задач", "➕ Новая задача"],
        ["⚙️ Настройки", "ℹ️ Помощь"],
    ],
    resize_keyboard=True,
)

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def get_user_tasks(user_id: int) -> list:
    return tasks.setdefault(user_id, [])

def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Удаляет задание из JobQueue по имени, если оно есть."""
    current_jobs = context.application.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True

# ---------- КОМАНДЫ И ОБРАБОТЧИКИ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение при /start."""
    user = update.effective_user
    text = (
        f"👋 Привет, {user.first_name}! Я твой личный занудный помощник.\n"
        "Я буду следить за каждым твоим шагом, записывать всякие мелочи "
        "и напоминать о них, пока ты не взвоешь.\n"
        "Готов? Тогда начнём!\n"
        "Используй кнопки меню, и не вздумай меня игнорировать."
    )
    await update.message.reply_text(text, reply_markup=main_keyboard)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выход из любого диалога."""
    await update.message.reply_text(
        "Ну и ладно! Очень надо было… Обращайся, если передумаешь.",
        reply_markup=main_keyboard,
    )
    return ConversationHandler.END

# --- Добавление задачи (ConversationHandler) ---
async def new_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало диалога: запрос названия задачи."""
    await update.message.reply_text(
        "📝 Как назовём твою задачку? Давай, не стесняйся.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return TITLE

async def new_task_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняем название, спрашиваем дедлайн."""
    context.user_data["new_title"] = update.message.text
    keyboard = [[InlineKeyboardButton("Пропустить", callback_data="skip_deadline")]]
    await update.message.reply_text(
        "Ага, понял. Теперь скажи дедлайн (в любом виде) или нажми «Пропустить», "
        "если тебе всё равно.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DEADLINE

async def new_task_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем дедлайн (или пропускаем)."""
    query = update.callback_query
    if query:
        await query.answer()
        deadline = None
        message = query.message
        # Отредактируем сообщение, убрав клавиатуру
        await message.edit_text("Дедлайн пропущен. Живи в хаосе.")
    else:
        deadline = update.message.text
        message = update.message
        await message.reply_text(f"Записал дедлайн: «{deadline}». Серьёзно?")

    context.user_data["new_deadline"] = deadline

    # Спрашиваем про напоминание
    keyboard = [
        [
            InlineKeyboardButton("Да, напомни", callback_data="remind_yes"),
            InlineKeyboardButton("Нет, сам справлюсь", callback_data="remind_no"),
        ]
    ]
    await message.reply_text(
        "Хочешь, чтобы я тебе надоедал с напоминанием об этой задаче?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WANT_REMINDER

async def new_task_reminder_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатываем выбор напоминания."""
    query = update.callback_query
    await query.answer()
    choice = query.data
    if choice == "remind_no":
        context.user_data["new_remind_minutes"] = None
        await query.message.reply_text(
            "Ну как хочешь. Я запомню, но потом не жалуйся, что забыл."
        )
        return await ask_confirmation(update, context, query.message)
    else:
        await query.message.reply_text(
            "Через сколько минут тебе напомнить? Отправь просто число."
        )
        return REMINDER_TIME

async def new_task_reminder_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем количество минут для напоминания."""
    text = update.message.text
    if not text.isdigit():
        await update.message.reply_text("Это не число! Попробуй ещё раз:")
        return REMINDER_TIME
    minutes = int(text)
    if minutes <= 0:
        await update.message.reply_text("Должно быть больше нуля. Ну же:")
        return REMINDER_TIME
    context.user_data["new_remind_minutes"] = minutes
    await update.message.reply_text(f"Ладно, напомню через {minutes} мин.")
    return await ask_confirmation(update, context, update.message)

async def ask_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message
):
    """Выводим итог и спрашиваем подтверждение добавления."""
    title = context.user_data.get("new_title", "???")
    deadline = context.user_data.get("new_deadline")
    remind = context.user_data.get("new_remind_minutes")

    summary = f"📌 Название: {title}\n"
    summary += f"📅 Дедлайн: {deadline if deadline else 'не указан'}\n"
    summary += f"⏰ Напоминание: {'через ' + str(remind) + ' мин.' if remind else 'нет'}\n"
    summary += "\nТы точно хочешь это сохранить? Потом не отвертишься."

    keyboard = [
        [
            InlineKeyboardButton("✅ Да, добавить", callback_data="confirm_yes"),
            InlineKeyboardButton("❌ Нет, отмена", callback_data="confirm_no"),
        ]
    ]
    await message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM

async def new_task_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финальное подтверждение: добавляем задачу."""
    query = update.callback_query
    await query.answer()
    if query.data == "confirm_no":
        await query.message.reply_text(
            "Пфф, передумал. Конечно, я так и знал.",
            reply_markup=main_keyboard,
        )
        context.user_data.clear()
        return ConversationHandler.END

    # Сохраняем задачу
    user_id = update.effective_user.id
    task_id = len(get_user_tasks(user_id)) + 1
    title = context.user_data["new_title"]
    deadline = context.user_data["new_deadline"]
    remind_minutes = context.user_data["new_remind_minutes"]

    # Настройка напоминания
    job_name = None
    if remind_minutes:
        job_name = f"remind_{user_id}_{task_id}"
        context.application.job_queue.run_once(
            remind_callback,
            when=remind_minutes * 60,
            data={"user_id": user_id, "title": title, "task_id": task_id},
            name=job_name,
        )

    get_user_tasks(user_id).append(
        {
            "id": task_id,
            "title": title,
            "deadline": deadline,
            "remind_job": job_name,
        }
    )

    await query.message.reply_text(
        f"Всё, записал задачку №{task_id}. Доволен? Теперь не смей забыть!",
        reply_markup=main_keyboard,
    )
    context.user_data.clear()
    return ConversationHandler.END

async def remind_callback(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет напоминание."""
    data = context.job.data
    await context.bot.send_message(
        chat_id=data["user_id"],
        text=f"⏰ Эй! Ты просил напомнить: «{data['title']}»\n"
        f"Давай, действуй! Не отлынивай.",
    )

# --- Просмотр и удаление задач ---
async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список задач с кнопками управления."""
    user_id = update.effective_user.id
    user_tasks = get_user_tasks(user_id)

    if not user_tasks:
        await update.message.reply_text(
            "У тебя пока нет задач. Как насчёт добавить одну, а?",
            reply_markup=main_keyboard,
        )
        return

    lines = ["📋 *Твои задачи:*\n"]
    keyboard = []
    for task in user_tasks:
        tid = task["id"]
        title = task["title"]
        deadline = f" (📅 {task['deadline']})" if task["deadline"] else ""
        lines.append(f"*{tid}.* {title}{deadline}")
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"❌ Удалить {tid}", callback_data=f"del_{tid}"
                ),
                InlineKeyboardButton(
                    f"✅ Выполнено {tid}", callback_data=f"done_{tid}"
                ),
            ]
        )

    text = "\n".join(lines)
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def handle_task_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление или пометка выполненной задачи."""
    query = update.callback_query
    await query.answer()
    data = query.data

    user_id = query.from_user.id
    user_tasks = get_user_tasks(user_id)

    if data.startswith("del_"):
        task_id = int(data.split("_")[1])
        # Ищем задачу по id
        task = next((t for t in user_tasks if t["id"] == task_id), None)
        if not task:
            await query.message.reply_text("Эта задача уже удалена или не существует.")
            return
        # Подтверждение удаления (нудность)
        keyboard = [
            [
                InlineKeyboardButton(
                    "Да, удалить навсегда", callback_data=f"confirmdel_{task_id}"
                ),
                InlineKeyboardButton("Нет, оставить", callback_data="cancel_del"),
            ]
        ]
        await query.message.reply_text(
            f"Ты правда хочешь удалить задачу «{task['title']}»? "
            "Это необратимо!",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("done_"):
        task_id = int(data.split("_")[1])
        task = next((t for t in user_tasks if t["id"] == task_id), None)
        if task:
            # Удаляем напоминание если есть
            if task.get("remind_job"):
                remove_job_if_exists(task["remind_job"], context)
            user_tasks[:] = [t for t in user_tasks if t["id"] != task_id]
            await query.message.reply_text(
                f"Молодец, что выполнил «{task['title']}»! "
                "Но мог бы и раньше…",
                reply_markup=main_keyboard,
            )
        else:
            await query.message.reply_text("Не могу найти эту задачу. Странно.")

    elif data.startswith("confirmdel_"):
        task_id = int(data.split("_")[1])
        task = next((t for t in user_tasks if t["id"] == task_id), None)
        if task:
            if task.get("remind_job"):
                remove_job_if_exists(task["remind_job"], context)
            user_tasks[:] = [t for t in user_tasks if t["id"] != task_id]
            await query.message.reply_text(
                f"Удалил «{task['title']}». Но это было больно для меня.",
                reply_markup=main_keyboard,
            )
        else:
            await query.message.reply_text("Уже удалено. Не накручивай.")

    elif data == "cancel_del":
        await query.message.reply_text(
            "Фух, оставляем. Береги свои задачи.",
            reply_markup=main_keyboard,
        )

# --- Прочие экраны ---
async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ Настройки пока в разработке. Но я и так достаточно навязчив.",
        reply_markup=main_keyboard,
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Я — занудный планировщик. Вот что я умею:\n"
        "• Добавлять задачи (спрашиваю кучу деталей)\n"
        "• Показывать список с кнопками удаления\n"
        "• Напоминать о задачах через заданное время\n"
        "• Ныть, если ты передумал\n\n"
        "Команды: /start, /tasks, /cancel",
        reply_markup=main_keyboard,
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error(msg="Ошибка:", exc_info=context.error)
    if update and hasattr(update, "message") and update.message:
        await update.message.reply_text("Произошла ошибка. Но я всё равно недоволен.")
    elif update and hasattr(update, "callback_query") and update.callback_query:
        await update.callback_query.answer("Произошла ошибка. Но я всё равно недоволен.")

# ---------- СБОРКА ПРИЛОЖЕНИЯ ----------
async def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    application = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler для добавления задачи
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^➕ Новая задача$"), new_task_start),
            CommandHandler("new", new_task_start),
        ],
        states={
            TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, new_task_title)
            ],
            DEADLINE: [
                CallbackQueryHandler(new_task_deadline, pattern="^skip_deadline$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, new_task_deadline),
            ],
            WANT_REMINDER: [
                CallbackQueryHandler(
                    new_task_reminder_choice, pattern="^remind_"
                )
            ],
            REMINDER_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, new_task_reminder_time)
            ],
            CONFIRM: [
                CallbackQueryHandler(new_task_confirm, pattern="^confirm_")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("tasks", show_tasks))
    application.add_handler(
        MessageHandler(filters.Regex("^📋 Список задач$"), show_tasks)
    )
    application.add_handler(conv_handler)
    application.add_handler(
        MessageHandler(filters.Regex("^⚙️ Настройки$"), settings)
    )
    application.add_handler(
        MessageHandler(filters.Regex("^ℹ️ Помощь$"), help_cmd)
    )
    application.add_handler(CallbackQueryHandler(handle_task_action))
    application.add_error_handler(error_handler)

    # Запуск
    print("Бот запущен. Нажмите Ctrl+C для остановки.")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    # Держим бота живым
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
