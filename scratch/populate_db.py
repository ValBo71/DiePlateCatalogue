import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'catalog.db')
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')

# Standard vector drawings (SVGs) to generate if missing
SVG_TEMPLATES = {
    "die_box_fefco0201.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500" width="100%" height="100%">
  <rect width="800" height="500" fill="#fcfcfc" stroke="#eee" stroke-width="2"/>
  <text x="30" y="40" font-family="'Courier New', monospace" font-size="16" font-weight="bold" fill="#333">ЧЕРТЕЖ: ЩАНЦА ЗА КАШОН (FEFCO 0201)</text>
  <line x1="30" y1="60" x2="150" y2="60" stroke="#ff0000" stroke-width="2"/>
  <text x="160" y="65" font-family="sans-serif" font-size="11" fill="#666">Рязане (Нож)</text>
  <line x1="300" y1="60" x2="420" y2="60" stroke="#0000ff" stroke-width="2" stroke-dasharray="4,4"/>
  <text x="430" y="65" font-family="sans-serif" font-size="11" fill="#666">Сгъване (Биг)</text>
  <g transform="translate(50, 100)">
    <path d="M 0,100 L 30,120 L 30,280 L 0,300 Z" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 30,100 L 230,100 M 230,100 L 230,100 M 30,300 L 230,300" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 30,100 L 30,0 L 230,0 L 230,100" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 30,300 L 30,400 L 230,400 L 230,300" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 230,100 L 380,100 M 230,300 L 380,300" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 230,100 L 230,0 L 380,0 L 380,100" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 230,300 L 230,400 L 380,400 L 380,300" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 380,100 L 580,100 M 380,300 L 580,300" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 380,100 L 380,0 L 580,0 L 580,100" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 380,300 L 380,400 L 580,400 L 580,300" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 580,100 L 730,100 M 580,300 L 730,300" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 580,100 L 580,0 L 730,0 L 730,100" fill="none" stroke="#ff0000" stroke-width="2" />
    <path d="M 580,300 L 580,400 L 730,400 L 730,300" fill="none" stroke="#ff0000" stroke-width="2" />
    <line x1="730" y1="100" x2="730" y2="300" stroke="#ff0000" stroke-width="2" />
    <line x1="30" y1="100" x2="730" y2="100" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
    <line x1="30" y1="300" x2="730" y2="300" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
    <line x1="30" y1="100" x2="30" y2="300" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
    <line x1="230" y1="100" x2="230" y2="300" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
    <line x1="380" y1="100" x2="380" y2="300" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
    <line x1="580" y1="100" x2="580" y2="300" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
    <text x="130" y="210" font-family="monospace" font-size="12" fill="#555" text-anchor="middle">L = 200</text>
    <text x="305" y="210" font-family="monospace" font-size="12" fill="#555" text-anchor="middle">W = 150</text>
    <text x="480" y="210" font-family="monospace" font-size="12" fill="#555" text-anchor="middle">L = 200</text>
    <text x="655" y="210" font-family="monospace" font-size="12" fill="#555" text-anchor="middle">W = 150</text>
    <text x="750" y="200" font-family="monospace" font-size="12" fill="#555" text-anchor="middle" transform="rotate(90, 750, 200)">H = 150</text>
  </g>
</svg>""",
    "die_folder.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 500" width="100%" height="100%">
  <rect width="600" height="500" fill="#fcfcfc" stroke="#eee" stroke-width="2"/>
  <text x="30" y="40" font-family="'Courier New', monospace" font-size="16" font-weight="bold" fill="#333">ЧЕРТЕЖ: ЩАНЦА ЗА ПАПКА А4 С ДЖОБ</text>
  <g transform="translate(100, 80)">
    <path d="M 0,0 L 190,0 Q 200,0 200,10 L 200,280 L 310,280 Q 320,280 320,290 L 320,380 L 10,380 Q 0,380 0,370 L 0,0 Z" fill="none" stroke="#ff0000" stroke-width="2"/>
    <path d="M 200,10 L 390,10 Q 400,10 400,20 L 400,290 L 200,290" fill="none" stroke="#ff0000" stroke-width="2"/>
    <path d="M 50,330 L 100,330 M 75,320 L 75,340" fill="none" stroke="#ff0000" stroke-width="1.5" />
    <path d="M 120,330 L 170,330 M 145,320 L 145,340" fill="none" stroke="#ff0000" stroke-width="1.5" />
    <line x1="200" y1="10" x2="200" y2="290" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
    <line x1="0" y1="290" x2="200" y2="290" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
    <line x1="320" y1="290" x2="320" y2="380" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
  </g>
</svg>""",
    "die_envelope.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 500" width="100%" height="100%">
  <rect width="600" height="500" fill="#fcfcfc" stroke="#eee" stroke-width="2"/>
  <text x="30" y="40" font-family="'Courier New', monospace" font-size="16" font-weight="bold" fill="#333">ЧЕРТЕЖ: ЩАНЦА ЗА ПЛИК (C6 POCKET)</text>
  <g transform="translate(150, 80)">
    <path d="M 50,0 L 250,0 L 270,50 L 30,50 Z" fill="none" stroke="#ff0000" stroke-width="2"/>
    <path d="M 30,50 L 0,60 L 0,220 L 30,230 Z" fill="none" stroke="#ff0000" stroke-width="2"/>
    <path d="M 270,50 L 300,60 L 300,220 L 270,230 Z" fill="none" stroke="#ff0000" stroke-width="2"/>
    <path d="M 30,230 L 50,350 L 250,350 L 270,230" fill="none" stroke="#ff0000" stroke-width="2"/>
    <line x1="30" y1="50" x2="270" y2="50" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
    <line x1="30" y1="230" x2="270" y2="230" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
    <line x1="30" y1="50" x2="30" y2="230" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
    <line x1="270" y1="50" x2="270" y2="230" stroke="#0000ff" stroke-width="2" stroke-dasharray="6,4" />
  </g>
</svg>"""
}

def populate():
    # 1. Ensure uploads directory exists and generate SVG drawings if missing
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    for name, content in SVG_TEMPLATES.items():
        file_path = os.path.join(UPLOADS_DIR, name)
        if not os.path.exists(file_path):
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Generated missing drawing: {name}")

    # 2. Database setup
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)
    
    print(f"Connecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Ensure database table and columns exist
    c.execute('''
        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            client TEXT,
            dimensions TEXT,
            location TEXT,
            image_filename TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Run migrations for new columns
    c.execute("PRAGMA table_info(tools)")
    columns = [row[1] for row in c.fetchall()]
    
    if 'die_shape' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN die_shape TEXT")
    if 'ups' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN ups INTEGER DEFAULT 1")
    if 'material' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN material TEXT")
    if 'die_type' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN die_type TEXT")
    if 'single_item_dimensions' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN single_item_dimensions TEXT")
    if 'file_path' not in columns:
        c.execute("ALTER TABLE tools ADD COLUMN file_path TEXT")
        
    print("Database structure verified.")

    # Clean existing database to avoid duplicates
    c.execute("DELETE FROM tools")

    # Generate 28 mock records total (8 original + 20 new)
    mock_tools = [
        # --- ORIGINAL 8 ITEMS ---
        ('SH-0001', 'die', 'Кутия за вино с дръжка 750ml', 'Винарна Тракия', '650x450 mm', 'A-2-1', 'die_box_fefco0201.svg', 'active', 
         'Усилен нож за картон 350g/m2. Втори нож в комплекта.', 'box', 1, 'cardboard', 'flat', '90x90x320 mm', r'D:\Чертежи\Вино_750ml.dxf'),
         
        ('SH-0002', 'die', 'Рондели / Кръгли етикети ф60', 'Bio Cosmetique', '450x450 mm', 'B-1-5', None, 'active',
         'Подходяща за самозалепваща хартия и тънък пластмасов филм.', 'circle', 4, 'paper', 'flat', 'ф60 mm', ''),
         
        ('SH-0003', 'die', 'Фирмена Папка А4 с джоб', 'Медия Дизайн', '700x500 mm', 'C-4-2', 'die_folder.svg', 'active',
         'Папка със закопчалка и джоб с прорези за визитка.', 'folder', 1, 'cardboard', 'flat', '215x305 mm', r'D:\Чертежи\Папка_А4.ai'),
         
        ('SH-0004', 'die', 'Ротационна щанца за кашони - тип 0201', 'Агро Пак', '1200x800 mm', 'D-1-1', 'die_box_fefco0201.svg', 'active',
         'Цилиндрична щанца за ротационна машина. Предназначена за трислойно велпапе.', 'box', 1, 'corrugated', 'cylindrical', '400x300x200 mm', r'D:\Чертежи\Кашон_0201.dxf'),

        ('PR-0001', 'embossing', 'Герб на Република България - Папка A4', 'Министерство на финансите', '80x85 mm', 'P-1-2', None, 'active',
         'Магнезиево клише 3мм с патрица. Дълбочина на релефа 1.2мм за луксозен картон.', '', 1, '', '', '', ''),
         
        ('PR-0002', 'embossing', 'Релефно лого "Premium Chocolate"', 'Сладък Свят', '120x40 mm', 'P-2-6', None, 'active',
         'Месингово клише за дълъг тираж. Предназначено за шоколадови кутии.', '', 1, '', '', '', ''),

        ('TP-0001', 'foil', 'Златен надпис "Happy Birthday"', 'Поздравителни Картички АД', '110x30 mm', 'T-3-4', None, 'active',
         'Подходящо за златна фолио лента тип Kurz. Работи при 120-135 градуса.', '', 1, '', '', '', ''),
         
        ('TP-0002', 'foil', 'Холограмно лого 20x20', 'Секюрити Груп', '20x20 mm', 'T-1-1', None, 'active',
         'Клише за топъл печат с висока резолюция за холографски стикери против фалшификация.', '', 1, '', '', '', ''),

        # --- 20 NEW ITEMS FOR PAGINATION TESTING ---
        # 11 New Dies (SH-0005 to SH-0015)
        ('SH-0005', 'die', 'Кутия за бонбони 200g', 'Захарни Изделия АД', '500x400 mm', 'A-3-2', 'die_box_fefco0201.svg', 'active',
         'Щанца за шоколадови бонбони. Офсет картон 280g.', 'box', 2, 'cardboard', 'flat', '150x150x40 mm', r'D:\Designs\Candy_200g.dxf'),

        ('SH-0006', 'die', 'Кръгли стикери ф40', 'Пчелна Ферма Медец', '400x300 mm', 'B-2-1', None, 'active',
         'Щанца за самозалепващи се хартиени етикети за мед.', 'circle', 6, 'paper', 'flat', 'ф40 mm', ''),

        ('SH-0007', 'die', 'Пощенски Плик C6', 'Български Пощи', '550x400 mm', 'C-1-3', 'die_envelope.svg', 'active',
         'Шаблон за стандартни писма с капак и самозалепваща лента.', 'envelope', 2, 'paper', 'flat', '114x162 mm', r'D:\Designs\Envelope_C6.dxf'),

        ('SH-0008', 'die', 'Кутия за бурканчета 3х100ml', 'Органик Фуудс', '600x400 mm', 'A-3-8', 'die_box_fefco0201.svg', 'active',
         'С прозорчета за витринен изглед. Картон 300g.', 'box', 1, 'cardboard', 'flat', '240x80x80 mm', ''),

        ('SH-0009', 'die', 'Игрални Карти - класически размер', 'Казино Империал', '480x380 mm', 'C-4-9', None, 'active',
         'Висока прецизност, специален нож за пластмасови карти.', 'playing_cards', 54, 'plastic', 'plunger', '57x89 mm', r'D:\Designs\Cards_Classic.ai'),

        ('SH-0010', 'die', 'Овални етикети 80x50', 'Миролио Текстил', '350x250 mm', 'B-1-12', None, 'active',
         'Предназначена за висящи картонени етикети за дрехи.', 'oval', 8, 'cardboard', 'flat', '80x50 mm', ''),

        ('SH-0011', 'die', 'Папка за документи с дебел гръб 5мм', 'Адвокатско дружество Тодоров', '750x550 mm', 'C-4-4', 'die_folder.svg', 'active',
         'Увеличен капацитет, подходяща за папки с голям брой листа.', 'folder', 1, 'cardboard', 'flat', '220x310 mm', r'D:\Designs\Folder_5mm.ai'),

        ('SH-0012', 'die', 'Кутия за пица 32см', 'Пицария Наполи', '900x600 mm', 'D-2-4', 'die_box_fefco0201.svg', 'active',
         'Предназначена за микровелпапе (Е-вълна). Бързо сглобяване.', 'box', 1, 'corrugated', 'flat', '320x320x40 mm', r'D:\Designs\Pizza_32cm.dxf'),

        ('SH-0013', 'die', 'Закачалка за врата (Do Not Disturb)', 'Хотел Маринела', '500x350 mm', 'C-2-7', None, 'active',
         'Щанца с кръгъл отвор ф50 и прорез за лесно закачане на дръжка.', 'custom', 3, 'cardboard', 'flat', '90x220 mm', ''),

        ('SH-0014', 'die', 'Етикет за вино - луксозен контур', 'Шато Копса', '400x300 mm', 'B-3-2', None, 'active',
         'Фигурен нож с орнаменти за висок клас вина.', 'label', 4, 'paper', 'flat', '90x120 mm', r'D:\Designs\Label_Copsa.ai'),

        ('SH-0015', 'die', 'Транспортен кашон за 6 бутилки', 'Винарна Боровица', '1100x700 mm', 'D-1-8', 'die_box_fefco0201.svg', 'active',
         'Петслойно велпапе, подсилени бигове.', 'box', 1, 'corrugated', 'flat', '280x190x340 mm', r'D:\Designs\Carton_6bottles.dxf'),

        # 5 New Embossing Clichés (PR-0003 to PR-0007)
        ('PR-0003', 'embossing', 'Лого "Bio Cosmetic"', 'Органик Лаб', '60x60 mm', 'P-1-8', None, 'active',
         'Месингов клише-релеф за козметични туби.', '', 1, '', '', '', ''),

        ('PR-0004', 'embossing', 'Релефен орнамент - Коледна картичка', 'Картички БГ', '140x90 mm', 'P-3-1', None, 'active',
         'Клише със сложен детайл за празничен релеф.', '', 1, '', '', '', ''),

        ('PR-0005', 'embossing', 'Фирмен знак - Корпоративна папка', 'Софтуер Груп', '50x50 mm', 'P-1-15', None, 'active',
         'Дълбок магнезиев релеф 1.5мм.', '', 1, '', '', '', ''),

        ('PR-0006', 'embossing', 'Лого "Premium Coffee"', 'Блу Баг Кафе', '80x30 mm', 'P-2-9', None, 'active',
         'Месингова матрица с патрица за релеф на кутии кафе.', '', 1, '', '', '', ''),

        ('PR-0007', 'embossing', 'Текстура "Кожа" - корица на книга', 'Издателство Захарий Стоянов', '200x150 mm', 'P-4-1', None, 'active',
         'Слепо преге (голямо клише) за придобиване на кожена текстура върху картон.', '', 1, '', '', '', ''),

        # 4 New Hot Foil Clichés (TP-0003 to TP-0006)
        ('TP-0003', 'foil', 'Сребърни звезди - Опаковъчна хартия', 'Опаковки ООД', '150x150 mm', 'T-2-12', None, 'active',
         'Клише за топъл печат с холографско сребърно фолио.', '', 1, '', '', '', ''),

        ('TP-0004', 'foil', 'Меден надпис "Reserve" - винени етикети', 'Домейн Бойар', '90x25 mm', 'T-3-8', None, 'active',
         'Месингово клише за печат при висока скорост. Температура 130C.', '', 1, '', '', '', ''),

        ('TP-0005', 'foil', 'Лого "Royal Hotel" - визитки', 'Роял Груп', '40x40 mm', 'T-1-9', None, 'active',
         'Магнезиево клише за златен топъл печат върху памучен картон.', '', 1, '', '', '', ''),

        ('TP-0006', 'foil', 'Златна рамка - грамоти А4', 'Министерство на образованието', '280x190 mm', 'T-4-2', None, 'active',
         'Голямо клише за рамка на сертификати и почетни грамоти.', '', 1, '', '', '', ''),

        ('SH-0016', 'die', 'Кутия за козметика / крем 50ml', 'Биофарма ООД', '350x250 mm', 'A-1-9', None, 'active',
         'Щанца за козметични опаковки с допълнително крило за безопасност.', 'box', 4, 'cardboard', 'flat', '60x60x60 mm', r'D:\Designs\Cosmetic_50ml.dxf'),

        ('SH-0017', 'die', 'Кръгла подложка за чаши ф90', 'Бирария Халбите', '300x300 mm', 'B-1-18', None, 'active',
         'Щанца за бирени подложки от дебела попивателна мукава 1.5мм.', 'circle', 4, 'greyboard', 'flat', 'ф90 mm', ''),

        ('PR-0008', 'embossing', 'Текстурен орнамент за визитки', 'Дизайн Студио Елит', '90x50 mm', 'P-2-12', None, 'active',
         'Фин месингов релеф за визитки на премиум картон.', '', 1, '', '', '', ''),

        ('TP-0007', 'foil', 'Лого "Premium Quality" - стикери', 'Винпром Пещера', '50x50 mm', 'T-2-5', None, 'active',
         'Клише за златно гланцово фолио върху самозалепваща се хартия.', '', 1, '', '', '', '')
    ]

    for tool in mock_tools:
        c.execute('''
            INSERT INTO tools (code, category, name, client, dimensions, location, image_filename, status, notes, die_shape, ups, material, die_type, single_item_dimensions, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', tool)
        print(f"Inserted/Refreshed: {tool[0]} - {tool[2]} (CAD path: {tool[14] or 'None'})")

    conn.commit()
    conn.close()
    print("Done!")

if __name__ == '__main__':
    populate()
