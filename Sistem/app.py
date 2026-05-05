from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import pandas as pd
import random, os, re
import threading
import gspread
import time
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)
CORS(app)

# LOAD DATA DARI SHEETS

SPREADSHEET_ID = "1NHE5WPk9Uy6b3YYuwwIkWWiOXZcN5xgtGczxUXP7Khg"
SHEET_PETUGAS = "petugas"
SHEET_ADMIN = "admin"
SHEET_HISTORY = "history"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

spreadsheet = client.open_by_key(SPREADSHEET_ID)

def load_sheet(sheet_name):
    sheet = spreadsheet.worksheet(sheet_name)
    data = sheet.get_all_records()
    return pd.DataFrame(data).fillna("")

df = load_sheet(SHEET_PETUGAS)

# Parameter Algoritma Genetika

kebutuhan = {
    "Sabtu Sore": 6,
    "Minggu Pagi": 8,
    "Minggu Siang": 8,
    "Minggu Sore": 8,
    "Minggu Malam": 8
}

POP_SIZE = 100
GENERATIONS = 150
ELITISM_RATE = 0.1

pc = 0.8
pm = 0.05
PENALTY_DUPLIKASI = 20

fitness_cache = {}

def sanitize_filename(name):
    name = re.sub(r"[\/:\\\*\?\"<>\|]+", "", name)
    return name.replace(" ", "_") or "Tanpa_Tanggal"

def kandidat_bisa(waktu):
    return df[df["Jadwal_Bisa"].str.contains(waktu, regex=False)]

def kandidat_pengurus_anggota(waktu):
    kandidat = kandidat_bisa(waktu)
    pengurus = kandidat[kandidat["Status"].str.lower() == "Pengurus"]["Nama"].tolist()
    anggota = kandidat[kandidat["Status"].str.lower() == "Anggota"]["Nama"].tolist()
    return pengurus, anggota

def load_history():
    hist = load_sheet(SHEET_HISTORY)
    hist["Total_Tugas"] = hist["Total_Tugas"].fillna(0)
    return hist

# Fungsi Buat Individu

def buat_individu():
    individu = {}
    semua_petugas = df["Nama"].dropna().unique().tolist()
    
    for waktu, jumlah in kebutuhan.items():
        pengurus, anggota = kandidat_pengurus_anggota(waktu)
        total_kandidat = len(pengurus) + len(anggota)
        THRESHOLD = jumlah
        
        terpilih = []
        
        if total_kandidat >= THRESHOLD:
            if pengurus:
                terpilih.extend(random.sample(pengurus, min(2, len(pengurus))))
            sisa = jumlah - len(terpilih)
            if anggota and sisa > 0:
                terpilih.extend(random.sample(anggota, min(sisa, len(anggota))))
            kandidat_lain = list(set(pengurus + anggota) - set(terpilih))
            while len(terpilih) < jumlah and kandidat_lain:
                terpilih.append(random.choice(kandidat_lain))
        
        else:
            if pengurus:
                terpilih.extend(random.sample(pengurus, min(2, len(pengurus))))
            sisa = jumlah - len(terpilih)
            if anggota and sisa > 0:
                terpilih.extend(random.sample(anggota, min(sisa, len(anggota))))
            while len(terpilih) < jumlah:
                kandidat_random = random.choice(semua_petugas)
                if kandidat_random not in terpilih:
                    terpilih.append(kandidat_random)
        
        individu[waktu] = terpilih
    
    return individu

# Fungsi Hitung Fitness

def hitung_fitness(individu, history_df):
    key = tuple((waktu, tuple(sorted(anggota))) for waktu, anggota in individu.items())
    key = str(key)
    
    if key in fitness_cache:
        return fitness_cache[key]

    skor_history = 0
    penalty_duplikasi = 0
    semua_nama = []
    for anggota in individu.values():
        semua_nama.extend(anggota)
        for nama in anggota:
            total = int(history_df.at[nama, "Total_Tugas"]) if nama in history_df.index else 0
            skor_history += 1 / (1 + total)
    jumlah_duplikat = len(semua_nama) - len(set(semua_nama))
    penalty_duplikasi = jumlah_duplikat * PENALTY_DUPLIKASI
    fitness = skor_history - penalty_duplikasi
    fitness_cache[key] = fitness

    return fitness

# Fungsi Seleksi, Crossover, Mutasi

def tournament_selection(populasi, history_df, k=4):
    peserta = random.sample(populasi, k)
    return max(peserta, key=lambda ind: hitung_fitness(ind, history_df))

def crossover(p1, p2):
    if random.random() > pc:
        return p1.copy()

    waktu_list = list(kebutuhan.keys())
    cut1, cut2 = sorted(random.sample(range(len(waktu_list)), 2))

    child = {}
    for i, waktu in enumerate(waktu_list):
        if cut1 <= i <= cut2:
            child[waktu] = p2[waktu].copy()
        else:
            child[waktu] = p1[waktu].copy()

    return child

def mutasi(individu):
    if random.random() < pm:
        waktu = random.choice(list(kebutuhan.keys()))
        jumlah = kebutuhan[waktu]
        
        pengurus, anggota = kandidat_pengurus_anggota(waktu)
        total_kandidat = len(pengurus) + len(anggota)
        semua_petugas = df["Nama"].dropna().unique().tolist()
        THRESHOLD = jumlah
        
        terpilih = []
        
        if total_kandidat >= THRESHOLD:
            if pengurus:
                terpilih.extend(random.sample(pengurus, min(2, len(pengurus))))
            sisa = jumlah - len(terpilih)
            if anggota and sisa > 0:
                terpilih.extend(random.sample(anggota, min(sisa, len(anggota))))
            kandidat_lain = list(set(pengurus + anggota) - set(terpilih))
            while len(terpilih) < jumlah and kandidat_lain:
                terpilih.append(random.choice(kandidat_lain))
        else:
            if pengurus:
                terpilih.extend(random.sample(pengurus, min(2, len(pengurus))))
            sisa = jumlah - len(terpilih)
            if anggota and sisa > 0:
                terpilih.extend(random.sample(anggota, min(sisa, len(anggota))))
            while len(terpilih) < jumlah:
                kandidat_random = random.choice(semua_petugas)
                if kandidat_random not in terpilih:
                    terpilih.append(kandidat_random)
        
        individu[waktu] = terpilih
    
    return individu

# Route Generate Jadwal

@app.route("/generate", methods=["POST"])
def generate():
    start_time = time.time()

    fitness_cache = {}

    global df
    df = load_sheet(SHEET_PETUGAS)

    data = request.get_json(force=True)
    tanggal = sanitize_filename(data.get("tanggal", "Tanpa_Tanggal"))

    history_df = load_history().set_index("Nama")
    history_df["Total_Tugas"] = history_df["Total_Tugas"].fillna(0).astype(int)

    populasi = [buat_individu() for _ in range(POP_SIZE)]

    for _ in range(GENERATIONS):
        sorted_pop = sorted(
            populasi,
            key=lambda ind: hitung_fitness(ind, history_df),
            reverse=True
        )

        elite = sorted_pop[:max(2, int(POP_SIZE * ELITISM_RATE))]
        new_pop = elite.copy()

        while len(new_pop) < POP_SIZE:
            p1 = tournament_selection(populasi, history_df)
            p2 = tournament_selection(populasi, history_df)
            child = mutasi(crossover(p1, p2))
            new_pop.append(child)

        populasi = new_pop

    best = max(populasi, key=lambda ind: hitung_fitness(ind, history_df))

    hasil = []
    for waktu, anggota in best.items():
        for nama in anggota:
            hasil.append([waktu, nama])

    jadwal_df = pd.DataFrame(hasil, columns=["Waktu", "Nama"])

    threading.Thread(
        target=save_to_sheets,
        args=(hasil, tanggal),
        daemon=True
    ).start()

# Evaluasi hasil

    end_time = time.time()
    execution_time = end_time - start_time

    all_nama = jadwal_df["Nama"].tolist()
    total_duplikasi = len(all_nama) - len(set(all_nama))

    best_fitness = hitung_fitness(best, history_df)

    print("\n===== HASIL EVALUASI =====")
    print(f"Total Duplikasi : {total_duplikasi}")
    print(f"Waktu Eksekusi  : {execution_time:.2f} detik")
    print(f"Fitness         : {best_fitness:.2f}")
    print("==========================\n")

    return jsonify({
        "status": "success",
        "jadwal": jadwal_df.to_dict(orient="records")
    })

# Fungsi Simpan Hasil ke Google Spreadsheets

def save_to_sheets(hasil, tanggal):
    try:
        base = f"Jadwal {tanggal}"
        name = base
        i = 1

        existing = [ws.title for ws in spreadsheet.worksheets()]
        while name in existing:
            name = f"{base} ({i})"
            i += 1

        sh = spreadsheet.add_worksheet(title=name, rows="1000", cols="10")
        sh.append_row(["Waktu", "Nama"])
        sh.append_rows(hasil)

        history_sh = spreadsheet.worksheet(SHEET_HISTORY)
        rows = history_sh.get_all_records()

        mapping = {}
        for idx, row in enumerate(rows, start=2):
            mapping[str(row["Nama"]).strip()] = (idx, int(row.get("Total_Tugas", 0) or 0))

        df_tmp = pd.DataFrame(hasil, columns=["Waktu", "Nama"])
        freq = df_tmp["Nama"].value_counts()

        updates = []
        for nama, jml in freq.items():
            if nama in mapping:
                row_idx, current = mapping[nama]
                updates.append({
                    "range": f"B{row_idx}",
                    "values": [[current + int(jml)]]
                })

        if updates:
            history_sh.batch_update(updates)

    except Exception as e:
        print("ERROR SAVE:", e)

# Routes Lainnya (Login, CRUD Petugas, dll)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/admin")
def admin_page():
    return render_template("admin.html")

@app.route("/update")
def update_page():
    return render_template("update.html")

@app.route("/manage")
def manage_page():
    return render_template("manage.html")

@app.route("/user-login", methods=["POST"])
def login_user():
    try:
        data = request.get_json(silent=True) or {}

        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()

        if not username or not password:
            return jsonify({
                "status": "error",
                "message": "Username / password kosong"
            }), 400

        df_petugas = load_sheet(SHEET_PETUGAS)

        df_petugas["Username"] = df_petugas["Username"].fillna("").astype(str).str.strip()
        df_petugas["Password"] = df_petugas["Password"].fillna("").astype(str).str.strip()

        user = df_petugas[
            (df_petugas["Username"] == username) &
            (df_petugas["Password"] == password)
        ]

        if user.empty:
            return jsonify({
                "status": "error",
                "message": "Username atau password salah"
            }), 401

        row = user.iloc[0]

        return jsonify({
            "status": "success",
            "username": row["Username"],
            "nama": row["Nama"],
            "jadwal": row["Jadwal_Bisa"]
        }), 200

    except Exception as e:
        print("ERROR login_user:", e)
        return jsonify({
            "status": "error",
            "message": "Terjadi kesalahan di server"
        }), 500


@app.route("/admin-login", methods=["POST"])
def admin_login():
    try:
        data = request.get_json()
        password = data.get("password", "").strip()

        df_admin = load_sheet(SHEET_ADMIN).astype(str)

        admin_pass = df_admin.iloc[0]["Password"].strip()

        if password == admin_pass:
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/add-petugas", methods=["POST"])
def add_petugas():
    data = request.get_json()

    username_baru = (data.get("username") or "").strip()
    nama_baru = (data.get("nama") or "").strip()

    sheet = spreadsheet.worksheet(SHEET_PETUGAS)
    rows = sheet.get_all_records()

    for row in rows:
        username_lama = str(row.get("Username", "")).strip()
        nama_lama = str(row.get("Nama", "")).strip()

        if username_lama == username_baru:
            return jsonify({
                "status": "error",
                "message": "Username sudah digunakan"
            })

        if nama_lama == nama_baru:
            return jsonify({
                "status": "error",
                "message": "Nama sudah digunakan"
            })

    sheet.append_row([
        username_baru,
        data["password"],
        nama_baru,
        "Anggota",
        ", ".join(data.get("jadwal_bisa", []))
    ])

    history_sheet = spreadsheet.worksheet(SHEET_HISTORY)
    history_sheet.append_row([nama_baru, 0])

    return jsonify({"status": "success"})

@app.route("/get-petugas")
def get_petugas():
    df_petugas = load_sheet(SHEET_PETUGAS)

    df_petugas.columns = df_petugas.columns.str.strip()

    data = []
    for i, row in df_petugas.iterrows():
        data.append({
            "id": str(i + 2),
            "nama": str(row.get("Nama", "")).strip(),
            "status": str(row.get("Status", "Anggota")).strip()
        })

    return jsonify(data)

@app.route("/update-status/<id>", methods=["POST"])
def update_status(id):
    data = request.get_json()
    status = data.get("status")

    sheet = spreadsheet.worksheet(SHEET_PETUGAS)

    id = int(id)

    sheet.update_cell(id, 4, status)

    return jsonify({"status": "success"})

@app.route("/hapus-petugas/<id>", methods=["DELETE"])
def hapus_petugas(id):

    sheet = spreadsheet.worksheet(SHEET_PETUGAS)
    history_sheet = spreadsheet.worksheet(SHEET_HISTORY)

    id = int(id)

    nama = sheet.cell(id, 3).value
    sheet.delete_rows(id)
    rows = history_sheet.get_all_records()

    for i, row in enumerate(rows, start=2):
        if str(row["Nama"]).strip() == str(nama).strip():
            history_sheet.delete_rows(i)
            break
    
    return jsonify({"status": "success"})

@app.route("/reset_history", methods=["POST"])
def reset_history():
    try:
        sheet = spreadsheet.worksheet(SHEET_HISTORY)

        rows = sheet.get_all_values()

        updates = []

        for i in range(2, len(rows) + 1):
            updates.append({
                "range": f"B{i}",
                "values": [[0]]
            })

        if updates:
            sheet.batch_update(updates)

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
@app.route("/change_admin_password", methods=["POST"])
def change_admin_password():
    try:
        data = request.get_json()
        new_pass = (data.get("new_password") or "").strip()

        if not new_pass:
            return jsonify({"status": "error", "message": "Password kosong"})

        sheet = spreadsheet.worksheet(SHEET_ADMIN)

        sheet.update(range_name="A2", values=[[new_pass]])

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/get_user_data", methods=["POST"])
def get_user_data():
    try:
        data = request.get_json(silent=True) or {}
        username = (data.get("username") or "").strip()

        if not username:
            return jsonify({"status": "error", "message": "Username kosong"}), 400

        df_petugas = load_sheet(SHEET_PETUGAS)

        required_cols = ["Username", "Password", "Nama", "Status", "Jadwal_Bisa"]
        for col in required_cols:
            if col not in df_petugas.columns:
                return jsonify({
                    "status": "error",
                    "message": f"Kolom '{col}' tidak ditemukan"
                }), 500

        df_petugas["Username"] = df_petugas["Username"].fillna("").astype(str).str.strip()
        df_petugas["Password"] = df_petugas["Password"].fillna("").astype(str)
        df_petugas["Nama"] = df_petugas["Nama"].fillna("").astype(str)
        df_petugas["Status"] = df_petugas["Status"].fillna("").astype(str)
        df_petugas["Jadwal_Bisa"] = df_petugas["Jadwal_Bisa"].fillna("").astype(str)

        user = df_petugas.loc[df_petugas["Username"] == username]

        if user.empty:
            return jsonify({
                "status": "error",
                "message": f"User '{username}' tidak ditemukan"
            }), 404

        row = user.iloc[0]

        return jsonify({
            "status": "success",
            "username": username,
            "password": row["Password"],
            "nama": row["Nama"],
            "status_user": row["Status"],
            "jadwal_bisa": row["Jadwal_Bisa"]
        }), 200

    except Exception as e:
        print("ERROR get_user_data:", e)
        return jsonify({
            "status": "error",
            "message": "Terjadi kesalahan di server"
        }), 500
    
@app.route("/update_user", methods=["POST"])
def update_user():
    try:
        data = request.get_json()

        username_lama = (data.get("username_lama") or "").strip()
        username_baru = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        nama_baru = (data.get("nama") or "").strip()
        status = (data.get("status") or "").strip()

        jadwal_raw = data.get("jadwal_bisa", [])
        jadwal_bisa = ", ".join(jadwal_raw) if isinstance(jadwal_raw, list) else str(jadwal_raw)

        sheet = spreadsheet.worksheet(SHEET_PETUGAS)
        history_sheet = spreadsheet.worksheet(SHEET_HISTORY)

        rows = sheet.get_all_values()

        target_row = None
        nama_lama = None

        for i, row in enumerate(rows[1:], start=2):
            if len(row) < 5:
                continue

            if row[0].strip() == username_lama:
                target_row = i
                nama_lama = row[2].strip()
                break

        if not target_row:
            return jsonify({"status": "error", "message": "User tidak ditemukan"})

        for i, row in enumerate(rows[1:], start=2):
            if len(row) < 5:
                continue

            username_sheet = row[0].strip()
            nama_sheet = row[2].strip()

            if i == target_row:
                continue

            if username_sheet == username_baru:
                return jsonify({
                    "status": "error",
                    "message": "Username sudah digunakan"
                })

            if nama_sheet == nama_baru:
                return jsonify({
                    "status": "error",
                    "message": "Nama sudah digunakan"
                })

        sheet.update(range_name=f"A{target_row}:E{target_row}", values=[[
            username_baru,
            password,
            nama_baru,
            status,
            jadwal_bisa
        ]])

        if nama_lama != nama_baru:
            history_rows = history_sheet.get_all_records()

            for j, hrow in enumerate(history_rows, start=2):
                if str(hrow["Nama"]).strip() == nama_lama:
                    history_sheet.update(
                        range_name=f"A{j}",
                        values=[[nama_baru]]
                    )
                    break

        return jsonify({"status": "success"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/latest-schedule")
def latest_schedule():
    try:
        worksheets = spreadsheet.worksheets()

        jadwal_sheets = [
            ws for ws in worksheets
            if ws.title.startswith("Jadwal")
        ]

        if not jadwal_sheets:
            return jsonify({"status": "empty"})

        latest_sheet = jadwal_sheets[-1]

        data = latest_sheet.get_all_records()

        if not data:
            return jsonify({"status": "empty"})

        return jsonify({
            "status": "success",
            "filename": latest_sheet.title,
            "data": data
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
