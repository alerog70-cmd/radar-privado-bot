import os
import logging
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 5299969756

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ==================== BASE DE DATOS ====================
def init_db():
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            telegram_id INTEGER PRIMARY KEY,
            nombre TEXT,
            edad INTEGER,
            busca TEXT,
            zona TEXT,
            fecha_registro TEXT,
            es_premium INTEGER DEFAULT 0,
            premium_hasta TEXT,
            foto_id TEXT
        )
    """)
    for col in ["es_premium INTEGER DEFAULT 0", "premium_hasta TEXT", "foto_id TEXT"]:
        try:
            c.execute(f"ALTER TABLE usuarios ADD COLUMN {col}")
        except:
            pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS intereses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            de_id INTEGER,
            para_id INTEGER,
            fecha TEXT,
            UNIQUE(de_id, para_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS intereses_diarios (
            telegram_id INTEGER,
            fecha TEXT,
            cantidad INTEGER DEFAULT 0,
            PRIMARY KEY (telegram_id, fecha)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS chats_activos (
            user_id INTEGER PRIMARY KEY,
            con_quien INTEGER,
            fecha TEXT
        )
    """)

    conn.commit()
    conn.close()

def guardar_usuario(telegram_id, nombre, edad, busca, zona, foto_id=None):
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO usuarios 
        (telegram_id, nombre, edad, busca, zona, fecha_registro, es_premium, premium_hasta, foto_id)
        VALUES (?, ?, ?, ?, ?, ?, 
            COALESCE((SELECT es_premium FROM usuarios WHERE telegram_id=?), 0),
            COALESCE((SELECT premium_hasta FROM usuarios WHERE telegram_id=?), NULL), ?)
    """, (telegram_id, nombre, edad, busca, zona, datetime.now().isoformat(), telegram_id, telegram_id, foto_id))
    conn.commit()
    conn.close()

def obtener_usuario(telegram_id):
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    c.execute("SELECT * FROM usuarios WHERE telegram_id=?", (telegram_id,))
    r = c.fetchone()
    conn.close()
    return r

def es_premium(telegram_id):
    d = obtener_usuario(telegram_id)
    if not d or len(d) < 8:
        return False
    if d[6] == 1:
        if d[7]:
            try:
                return datetime.fromisoformat(d[7]) > datetime.now()
            except:
                return True
        return True
    return False

def activar_premium(telegram_id, dias=30):
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    hasta = (datetime.now() + timedelta(days=dias)).isoformat()
    c.execute("UPDATE usuarios SET es_premium=1, premium_hasta=? WHERE telegram_id=?", (hasta, telegram_id))
    conn.commit()
    conn.close()

def obtener_otros_usuarios(telegram_id):
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    c.execute("""
        SELECT telegram_id, nombre, edad, busca, zona, foto_id 
        FROM usuarios WHERE telegram_id != ? 
        ORDER BY es_premium DESC, fecha_registro DESC LIMIT 15
    """, (telegram_id,))
    r = c.fetchall()
    conn.close()
    return r

def guardar_interes(de_id, para_id):
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO intereses (de_id, para_id, fecha) VALUES (?,?,?)",
                  (de_id, para_id, datetime.now().isoformat()))
        conn.commit()
    except:
        pass
    conn.close()

def hay_match(de_id, para_id):
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    c.execute("SELECT 1 FROM intereses WHERE de_id=? AND para_id=?", (para_id, de_id))
    r = c.fetchone()
    conn.close()
    return r is not None

def puede_enviar_interes(telegram_id):
    if es_premium(telegram_id):
        return True
    hoy = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    c.execute("SELECT cantidad FROM intereses_diarios WHERE telegram_id=? AND fecha=?", (telegram_id, hoy))
    r = c.fetchone()
    if r is None:
        c.execute("INSERT INTO intereses_diarios (telegram_id, fecha, cantidad) VALUES (?,?,1)", (telegram_id, hoy))
        conn.commit()
        conn.close()
        return True
    if r[0] >= 3:
        conn.close()
        return False
    c.execute("UPDATE intereses_diarios SET cantidad=cantidad+1 WHERE telegram_id=? AND fecha=?", (telegram_id, hoy))
    conn.commit()
    conn.close()
    return True

def obtener_interesados(telegram_id):
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    c.execute("""
        SELECT u.telegram_id, u.nombre, u.edad, u.busca, u.zona, u.foto_id
        FROM intereses i
        JOIN usuarios u ON u.telegram_id = i.de_id
        WHERE i.para_id = ?
        ORDER BY i.fecha DESC LIMIT 20
    """, (telegram_id,))
    r = c.fetchall()
    conn.close()
    return r

def obtener_matches(telegram_id):
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    c.execute("""
        SELECT u.telegram_id, u.nombre, u.edad, u.busca, u.zona, u.foto_id
        FROM intereses i1
        JOIN intereses i2 ON i1.de_id = i2.para_id AND i1.para_id = i2.de_id
        JOIN usuarios u ON u.telegram_id = i1.para_id
        WHERE i1.de_id = ?
    """, (telegram_id,))
    r = c.fetchall()
    conn.close()
    return r

def iniciar_chat(user_id, con_quien):
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO chats_activos (user_id, con_quien, fecha) VALUES (?,?,?)",
              (user_id, con_quien, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def obtener_chat_activo(user_id):
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    c.execute("SELECT con_quien FROM chats_activos WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None

def terminar_chat(user_id):
    conn = sqlite3.connect("radar_privado.db")
    c = conn.cursor()
    c.execute("DELETE FROM chats_activos WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data.clear()

    if obtener_usuario(user.id):
        teclado = [
            [InlineKeyboardButton("👤 Ver mi perfil", callback_data="ver_perfil")],
            [InlineKeyboardButton("✏️ Editar perfil", callback_data="editar_perfil")]
        ]
        await update.message.reply_text(
            f"Hola de nuevo, {user.first_name}.\n\n"
            "Tu perfil ya está activo.\n"
            "¿Qué deseas hacer?",
            reply_markup=InlineKeyboardMarkup(teclado)
        )
        return

    teclado = [[InlineKeyboardButton("✅ Acepto las reglas", callback_data="aceptar_reglas")]]
    await update.message.reply_text(
        f"Hola {user.first_name}.\n\n"
        "Bienvenido a *Radar Privado*.\n\n"
        "Un espacio discreto y seguro para conocer personas cerca de ti.\n"
        "Tu privacidad es lo más importante.\n\n"
        "Al continuar aceptas:\n"
        "• Ser mayor de 18 años\n"
        "• Respetar a los demás usuarios\n"
        "• No compartir información personal sin consentimiento\n\n"
        "Presiona el botón para comenzar:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(teclado)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "aceptar_reglas":
        context.user_data["estado"] = "esperando_edad"
        await query.edit_message_text(
            "Perfecto.\n\n"
            "Vamos a crear tu perfil discreto.\n\n"
            "¿Cuál es tu edad? (escribe solo el número)"
        )

    elif query.data.startswith("busca_"):
        opciones = {
            "busca_chat": "Chat",
            "busca_encuentro": "Encuentro",
            "busca_amistad": "Amistad",
            "busca_loquesurga": "Lo que surja"
        }
        context.user_data["busca"] = opciones[query.data]
        context.user_data["estado"] = "esperando_zona"
        await query.edit_message_text(
            f"Buscas: *{opciones[query.data]}*\n\n"
            "¿En qué zona te encuentras?\n"
            "Ejemplo: Cuerámaro o Cuerámaro y alrededores",
            parse_mode="Markdown"
        )

    elif query.data == "ver_perfil":
        datos = obtener_usuario(user.id)
        if not datos:
            await query.edit_message_text("No se encontró tu perfil.")
            return
        premium = "✅ Premium activo" if es_premium(user.id) else "Versión gratuita"
        texto = (
            f"👤 *Tu perfil*\n\n"
            f"• Nombre: {datos[1]}\n"
            f"• Edad: {datos[2]}\n"
            f"• Busca: {datos[3]}\n"
            f"• Zona: {datos[4]}\n"
            f"• Estado: {premium}\n"
            f"• Registrado: {datos[5][:10]}"
        )
        foto_id = datos[8] if len(datos) > 8 else None
        if foto_id:
            await query.message.reply_photo(photo=foto_id, caption=texto, parse_mode="Markdown")
            await query.delete_message()
        else:
            await query.edit_message_text(texto + "\n\n(Sin foto)", parse_mode="Markdown")

   elif query.data == "editar_perfil":
    # Cerrar chat activo si existe
    terminar_chat(user.id)
    context.user_data.clear()
    context.user_data["estado"] = "esperando_edad"
    await query.edit_message_text(
        "Vamos a actualizar tu perfil.\n\n"
        "¿Cuál es tu edad? (escribe solo el número)"
    )

    elif query.data == "saltar_foto":
        guardar_usuario(
            user.id, user.first_name,
            context.user_data.get("edad"),
            context.user_data.get("busca"),
            context.user_data.get("zona"),
            None
        )
        context.user_data["estado"] = "perfil_completo"
        await query.edit_message_text(
            "✅ *Perfil creado correctamente*\n\n"
            f"• Edad: {context.user_data.get('edad')}\n"
            f"• Busca: {context.user_data.get('busca')}\n"
            f"• Zona: {context.user_data.get('zona')}\n\n"
            "Ahora puedes usar /explorar para ver personas cerca de ti.",
            parse_mode="Markdown"
        )

    elif query.data.startswith("interes_"):
        para_id = int(query.data.split("_")[1])

        if not puede_enviar_interes(user.id):
            try:
                await query.edit_message_caption(
                    caption="Has alcanzado el límite de 3 intereses diarios.\n\n"
                            "⭐ Con Premium tienes intereses ilimitados.\n"
                            "Escribe /premium para más información."
                )
            except:
                await query.edit_message_text(
                    "Has alcanzado el límite de 3 intereses diarios.\n\n"
                    "⭐ Con Premium tienes intereses ilimitados.\n"
                    "Escribe /premium para más información."
                )
            return

        guardar_interes(user.id, para_id)

        if hay_match(user.id, para_id):
            try:
                await query.edit_message_caption(
                    caption="🔥 *¡Es un Match!*\n\n"
                            "Ambos se interesaron.\n"
                            "Usa /chat para empezar a hablar."
                )
            except:
                await query.edit_message_text(
                    "🔥 *¡Es un Match!*\n\n"
                    "Ambos se interesaron.\n"
                    "Usa /chat para empezar a hablar."
                )
            try:
                await context.bot.send_message(
                    chat_id=para_id,
                    text="🔥 *¡Tienes un nuevo Match!*\n\n"
                         "Alguien también te marcó interés.\n"
                         "Usa /chat para empezar a hablar."
                )
            except:
                pass
        else:
            try:
                await query.edit_message_caption(
                    caption="✅ Interés enviado.\n"
                            "Si la otra persona también te marca, será un Match."
                )
            except:
                await query.edit_message_text(
                    "✅ Interés enviado.\n"
                    "Si la otra persona también te marca, será un Match."
                )

    elif query.data.startswith("chat_con_"):
        con_quien = int(query.data.split("_")[2])
        iniciar_chat(user.id, con_quien)
        await query.edit_message_text(
            "✅ Chat iniciado.\n\n"
            "Ya puedes escribir. Tus mensajes se enviarán de forma anónima y discreta.\n\n"
            "Escribe /fin cuando quieras terminar la conversación."
        )

async def recibir_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    estado = context.user_data.get("estado")

    # Chat activo (solo si NO está creando/editando perfil)
estado = context.user_data.get("estado")
con_quien = obtener_chat_activo(user.id)

if con_quien and update.message.text and not update.message.text.startswith("/") and estado not in ["esperando_edad", "esperando_busca", "esperando_zona", "esperando_foto"]:
        try:
            await context.bot.send_message(
                chat_id=con_quien,
                text=f"💬 *Mensaje de tu Match:*\n\n{update.message.text}",
                parse_mode="Markdown"
            )
            await update.message.reply_text("✅ Mensaje enviado.")
        except:
            await update.message.reply_text("No se pudo enviar el mensaje.")
        return

    # Foto
    if update.message.photo and estado == "esperando_foto":
        foto_id = update.message.photo[-1].file_id
        guardar_usuario(
            user.id, user.first_name,
            context.user_data.get("edad"),
            context.user_data.get("busca"),
            context.user_data.get("zona"),
            foto_id
        )
        context.user_data["estado"] = "perfil_completo"
        await update.message.reply_text(
            "✅ *Perfil creado con foto*\n\n"
            f"• Edad: {context.user_data.get('edad')}\n"
            f"• Busca: {context.user_data.get('busca')}\n"
            f"• Zona: {context.user_data.get('zona')}\n\n"
            "Usa /explorar para ver personas cerca de ti.",
            parse_mode="Markdown"
        )
        return

    if not update.message.text:
        return

    texto = update.message.text.strip().lower()

    if texto == "pago":
        await update.message.reply_text(
            "💳 *Datos para activar Premium ($70 MXN / mes)*\n\n"
            "*Opción 1 – Transferencia SPEI:*\n"
            "Banco: Banco Azteca\n"
            "CLABE: 127180016586651634\n"
            "Nombre: Rafael Rodríguez\n\n"
            "*Opción 2 – Mercado Pago:*\n"
            "https://mpago.la/2UY55UU\n\n"
            "Una vez realizado el pago, envía el comprobante a este chat y te activaré Premium manualmente.",
            parse_mode="Markdown"
        )
        return

    if estado == "esperando_edad":
        if not update.message.text.isdigit():
            await update.message.reply_text("Por favor escribe solo el número de tu edad.")
            return
        edad = int(update.message.text)
        if edad < 18 or edad > 80:
            await update.message.reply_text("Debes tener entre 18 y 80 años.")
            return
        context.user_data["edad"] = edad
        context.user_data["estado"] = "esperando_busca"
        teclado = [
            [InlineKeyboardButton("Chat", callback_data="busca_chat")],
            [InlineKeyboardButton("Encuentro", callback_data="busca_encuentro")],
            [InlineKeyboardButton("Amistad", callback_data="busca_amistad")],
            [InlineKeyboardButton("Lo que surja", callback_data="busca_loquesurga")]
        ]
        await update.message.reply_text(
            f"Edad registrada: {edad} años.\n\n¿Qué estás buscando?",
            reply_markup=InlineKeyboardMarkup(teclado)
        )
        return

    if estado == "esperando_zona":
        context.user_data["zona"] = update.message.text.strip()
        context.user_data["estado"] = "esperando_foto"
        teclado = [[InlineKeyboardButton("Saltar foto", callback_data="saltar_foto")]]
        await update.message.reply_text(
            "¿Quieres agregar una foto a tu perfil?\n"
            "(Es opcional y se mostrará de forma discreta)\n\n"
            "Envía una foto o presiona el botón para continuar sin ella.",
            reply_markup=InlineKeyboardMarkup(teclado)
        )
        return

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    matches = obtener_matches(user.id)

    if not matches:
        await update.message.reply_text(
            "Todavía no tienes ningún Match.\n\n"
            "Sigue explorando con /explorar para encontrar personas."
        )
        return

    await update.message.reply_text(
        "🔥 *Tus Matches*\n\n"
        "Elige con quién quieres chatear:",
        parse_mode="Markdown"
    )

    for m in matches:
        tid, nombre, edad, busca, zona, foto_id = m
        texto = f"👤 *{nombre}* • {edad} años\nBusca: {busca}\nZona: {zona}"
        teclado = [[InlineKeyboardButton("💬 Chatear ahora", callback_data=f"chat_con_{tid}")]]

        if foto_id:
            await update.message.reply_photo(
                photo=foto_id, caption=texto, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(teclado)
            )
        else:
            await update.message.reply_text(
                texto, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(teclado)
            )

async def fin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    con_quien = obtener_chat_activo(user.id)
    if not con_quien:
        await update.message.reply_text("No tienes ningún chat activo en este momento.")
        return
    terminar_chat(user.id)
    await update.message.reply_text(
        "✅ Chat terminado.\n\n"
        "Puedes usar /chat cuando quieras hablar con otro Match."
    )

async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    datos = obtener_usuario(user.id)
    if not datos:
        await update.message.reply_text("Aún no tienes perfil.\nUsa /start para crear uno.")
        return
    premium = "✅ Premium activo" if es_premium(user.id) else "Versión gratuita"
    texto = (
        f"👤 *Tu perfil*\n\n"
        f"• Nombre: {datos[1]}\n"
        f"• Edad: {datos[2]}\n"
        f"• Busca: {datos[3]}\n"
        f"• Zona: {datos[4]}\n"
        f"• Estado: {premium}\n"
        f"• Registrado: {datos[5][:10]}"
    )
    foto_id = datos[8] if len(datos) > 8 else None
    if foto_id:
        await update.message.reply_photo(photo=foto_id, caption=texto, parse_mode="Markdown")
    else:
        await update.message.reply_text(texto + "\n\n(Sin foto)", parse_mode="Markdown")

async def explorar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    otros = obtener_otros_usuarios(user.id)
    if not otros:
        await update.message.reply_text(
            "Aún no hay más personas registradas cerca de ti.\n"
            "Vuelve a intentar más tarde."
        )
        return
    for p in otros:
        tid, nombre, edad, busca, zona, foto_id = p
        texto = f"👤 *{nombre}* • {edad} años\nBusca: {busca}\nZona: {zona}"
        teclado = [[InlineKeyboardButton("❤️ Me interesa", callback_data=f"interes_{tid}")]]
        if foto_id:
            await update.message.reply_photo(
                photo=foto_id, caption=texto, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(teclado)
            )
        else:
            await update.message.reply_text(
                texto, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(teclado)
            )

async def interesados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not es_premium(user.id):
        await update.message.reply_text(
            "⭐ *Función exclusiva de Premium*\n\n"
            "Con Premium puedes ver quién te ha marcado interés.\n\n"
            "Escribe /premium para conocer los beneficios.",
            parse_mode="Markdown"
        )
        return
    lista = obtener_interesados(user.id)
    if not lista:
        await update.message.reply_text("Todavía nadie te ha marcado interés.")
        return
    await update.message.reply_text(
        f"❤️ *Personas que te marcaron interés* ({len(lista)})",
        parse_mode="Markdown"
    )
    for persona in lista:
        tid, nombre, edad, busca, zona, foto_id = persona
        texto = f"👤 *{nombre}* • {edad} años\nBusca: {busca}\nZona: {zona}"
        teclado = [[InlineKeyboardButton("❤️ Me interesa también", callback_data=f"interes_{tid}")]]
        if foto_id:
            await update.message.reply_photo(photo=foto_id, caption=texto, parse_mode="Markdown",
                                             reply_markup=InlineKeyboardMarkup(teclado))
        else:
            await update.message.reply_text(texto, parse_mode="Markdown",
                                            reply_markup=InlineKeyboardMarkup(teclado))

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if es_premium(update.effective_user.id):
        await update.message.reply_text(
            "✅ Ya tienes *Premium* activo.\n\n"
            "Disfruta de todas las funciones sin límites.",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text(
        "⭐ *Radar Privado Premium*\n\n"
        "Desbloquea la experiencia completa:\n\n"
        "• Intereses *ilimitados* (la versión gratis solo permite 3 al día)\n"
        "• Ver *quién te marcó interés*\n"
        "• Apareces primero en las listas\n"
        "• Más posibilidades de Match y chats\n\n"
        "Precio: *Solo $70 MXN al mes*\n\n"
        "Escribe *pago* para ver los datos de transferencia o Mercado Pago.",
        parse_mode="Markdown"
    )

async def activar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("No tienes permiso para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso correcto:\n/activar <telegram_id>")
        return
    try:
        tid = int(context.args[0])
    except:
        await update.message.reply_text("El ID debe ser un número.")
        return
    if not obtener_usuario(tid):
        await update.message.reply_text("Ese usuario no tiene perfil registrado.")
        return
    activar_premium(tid)
    await update.message.reply_text(f"✅ Premium activado correctamente a {tid} por 30 días.")
    try:
        await context.bot.send_message(tid, "⭐ ¡Tu cuenta Premium ha sido activada por 30 días!\n\nYa tienes acceso a todas las funciones.")
    except:
        pass

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 *Comandos disponibles*\n\n"
        "/start - Iniciar o ver tu perfil\n"
        "/perfil - Ver tu perfil\n"
        "/explorar - Ver personas cerca\n"
        "/chat - Chatear con tus Matches\n"
        "/fin - Terminar el chat actual\n"
        "/interesados - Quién te marcó interés (Premium)\n"
        "/premium - Conocer los beneficios Premium\n"
        "/ayuda - Ver esta lista",
        parse_mode="Markdown"
    )

# ==================== MAIN ====================
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("perfil", perfil))
    app.add_handler(CommandHandler("explorar", explorar))
    app.add_handler(CommandHandler("chat", chat))
    app.add_handler(CommandHandler("fin", fin))
    app.add_handler(CommandHandler("interesados", interesados))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(CommandHandler("activar", activar))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, recibir_mensaje))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_mensaje))

    print("Bot iniciado correctamente. Presiona Ctrl+C para detenerlo.")
    app.run_polling()

if __name__ == "__main__":
    main()