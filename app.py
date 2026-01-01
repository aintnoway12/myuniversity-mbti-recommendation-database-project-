from flask import Flask, render_template, request, redirect, session
from db import get_connection
from datetime import datetime

app = Flask(__name__)
app.secret_key = "super_secret_123"

# ---------------------------------------------------------
# HOME → LOGIN
# ---------------------------------------------------------
@app.route("/")
def home():
    return redirect("/login")


# ---------------------------------------------------------
# LOGIN
# ---------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        user_id = request.form.get("user_id")
        password = request.form.get("password")

        conn = get_connection()
        cur = conn.cursor()

        # Student Login
        cur.execute("""
            SELECT student_id, name, mbti, nickname, year_level
            FROM Student
            WHERE student_id=%s 
              AND password=%s
              AND is_deleted=FALSE
        """, (user_id, password))

        row = cur.fetchone()

        if row:
            session.clear()
            session["user_id"] = row[0]
            session["user_name"] = row[1]
            session["user_type"] = "student"

            nickname = row[3]
            year_level = row[4]

            cur.close()
            conn.close()

            if not nickname or not year_level:
                return redirect("/profile-setup")

            return redirect("/dashboard")

        # Leader Login
        cur.execute("""
            SELECT club_id, name
            FROM club
            WHERE leader_id=%s AND leader_password=%s
        """, (user_id, password))
        leader = cur.fetchone()

        if leader:
            session.clear()
            session["user_type"] = "leader"
            session["user_id"] = user_id
            session["leader_club_id"] = leader[0]

            cur.close()
            conn.close()
            return redirect("/leader-dashboard")

        # Staff Login
        cur.execute("""
            SELECT staff_id, name
            FROM staff
            WHERE staff_id=%s AND password=%s
        """, (user_id, password))
        staff = cur.fetchone()

        if staff:
            session.clear()
            session["user_type"] = "staff"
            session["user_id"] = staff[0]
            session["user_name"] = staff[1]

            cur.close()
            conn.close()
            return redirect("/staff/home")

        cur.close()
        conn.close()
        error = "Invalid login information"

    return render_template("login.html", error=error)


# ---------------------------------------------------------
# PROFILE SETUP
# ---------------------------------------------------------
@app.route("/profile-setup", methods=["GET", "POST"])
def profile_setup():
    if "user_id" not in session or session["user_type"] != "student":
        return redirect("/login")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT major_id, major_name FROM Major ORDER BY major_name")
    majors = cur.fetchall()

    if request.method == "POST":
        nickname = request.form.get("nickname")
        major_id = request.form.get("major")
        year_level = request.form.get("year_level")
        mbti = request.form.get("mbti")
        preferred_time = request.form.get("preferred_time")

        cur.execute("""
            UPDATE Student
            SET nickname=%s,
                major_id=%s,
                year_level=%s,
                mbti=%s,
                preferred_time=%s,
                updated_at=NOW()
            WHERE student_id=%s
        """, (nickname, major_id, year_level, mbti, preferred_time, session["user_id"]))

        conn.commit()
        cur.close()
        conn.close()
        return redirect("/dashboard")

    cur.close()
    conn.close()
    return render_template("profile_setup.html", majors=majors)



# =========================================================
# DASHBOARD — MBTI + STYLE_PROFILE
# =========================================================
@app.route("/generate-mbti-recommendation")
def generate_mbti_recommendation():
    MBTI_SCORES = {
        "INTJ":  {"project": 5, "theory": 4, "presentation": 2},
        "INTP":  {"project": 5, "theory": 4},
        "INFJ":  {"presentation": 5, "discussion": 4},
        "INFP":  {"discussion": 5, "presentation": 3},
        "ISTJ":  {"theory": 5, "exam": 4},
        "ISTP":  {"lab": 5, "project": 4},
        "ISFJ":  {"presentation": 3, "assignment": 4},
        "ISFP":  {"creative": 5, "presentation": 4},
        "ENTJ":  {"project": 5, "presentation": 4},
        "ENTP":  {"discussion": 5, "presentation": 4},
        "ENFJ":  {"discussion": 5, "presentation": 4},
        "ENFP":  {"creative": 5, "presentation": 4},
        "ESTJ":  {"exam": 5, "project": 4},
        "ESTP":  {"lab": 5, "project": 4},
        "ESFJ":  {"presentation": 5, "assignment": 4},
        "ESFP":  {"presentation": 5, "creative": 4},
    }

    conn = get_connection()
    cur = conn.cursor()

    # 기존 추천 삭제
    cur.execute("DELETE FROM MBTIRecommendation")

    # 강의 목록 불러오기
    cur.execute("SELECT lecture_id, teaching_style FROM lecture")
    lectures = cur.fetchall()

    for mbti, styles in MBTI_SCORES.items():
        for lecture_id, teaching_style in lectures:

            style = (teaching_style or "").lower()

            score = styles.get(style, 1)  # 매칭 없으면 기본값 1
            reason = f"{mbti} → {style} 선호 점수 {score}"

            cur.execute("""
                INSERT INTO MBTIRecommendation (mbti, item_id, score, reason)
                VALUES (%s, %s, %s, %s)
            """, (mbti, lecture_id, score, reason))

    conn.commit()
    cur.close()
    conn.close()

    return "MBTI Recommendation 생성 완료!"



@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    student = session["user_id"]

    conn = get_connection()
    cur = conn.cursor()

    # Student Info
    cur.execute("""
        SELECT mbti, major_id, year_level, preferred_time
        FROM Student 
        WHERE student_id=%s
    """, (student,))
    mbti, major_id, year_level, preferred_time = cur.fetchone()

    def match_preferred_time(start, preferred):
        hour = int(str(start).split(":")[0])
        if preferred == "morning":
            return 9 <= hour < 12
        elif preferred == "afternoon":
            return 12 <= hour < 17
        elif preferred == "evening":
            return 17 <= hour < 21
        return True

    # -----------------------------------------------------
    # Major Recommendation
    # -----------------------------------------------------
    cur.execute("""
        SELECT l.lecture_id, 
               l.name,
               l.day,
               l.start_time,
               l.end_time,
               ml.category,
               l.description,
               COALESCE(r.score, 0),
               l.style_profile
        FROM Lecture l
        JOIN MajorLecture ml ON ml.lecture_id = l.lecture_id
        LEFT JOIN MBTIRecommendation r
            ON r.item_id = l.lecture_id
            AND (r.mbti=%s OR r.student_id=%s)
        WHERE ml.major_id = %s
    """, (mbti, student, major_id))

    major_rows = cur.fetchall()

    def compute_final_score(mbti_score, vec):
        if vec is None:
            return mbti_score
        vals = [int(x) for x in vec.split(",")]
        return mbti_score + sum(vals)

    major_by_year = {}
    for row in major_rows:
        lec_id, name, day, st, et, cat, desc, mbti_score, style_vec = row
        final = compute_final_score(mbti_score, style_vec)

        major_by_year.setdefault(cat, []).append({
            "lecture_id": lec_id,
            "name": name,
            "day": day,
            "start": st,
            "end": et,
            "description": desc,
            "score": final
        })

    for cat in major_by_year:
        major_by_year[cat].sort(key=lambda x: x["score"], reverse=True)

    # -----------------------------------------------------
    # Minor Recommendation
    # -----------------------------------------------------
    cur.execute("""
        SELECT l.lecture_id,
               l.name,
               l.day,
               l.start_time,
               l.end_time,
               ml.category,
               l.description,
               COALESCE(r.score, 0),
               ml.minor_id,
               l.style_profile
        FROM Lecture l
        JOIN MinorLecture ml ON ml.lecture_id = l.lecture_id
        LEFT JOIN MBTIRecommendation r
            ON r.item_id = l.lecture_id
            AND (r.mbti=%s OR r.student_id=%s)
    """, (mbti, student))

    minor_rows = cur.fetchall()

    cur.execute("SELECT minor_id, minor_name FROM Minor ORDER BY minor_id")
    minor_list = cur.fetchall()
    id_to_minor = {m[0]: m[1] for m in minor_list}
    minor_filtered = {m[1]: [] for m in minor_list}

    for row in minor_rows:
        lec_id, name, day, st, et, cat, desc, mbti_score, m_id, style_vec = row
        final = compute_final_score(mbti_score, style_vec)
        minor_name = id_to_minor.get(m_id)

        if minor_name:
            minor_filtered[minor_name].append({
                "lecture_id": lec_id,
                "name": name,
                "day": day,
                "start": st,
                "end": et,
                "description": desc,
                "score": final
            })

            if not match_preferred_time(st, preferred_time):
                continue

    for key in minor_filtered:
        minor_filtered[key].sort(key=lambda x: x["score"], reverse=True)

    # -----------------------------------------------------
    # Liked Course
    # -----------------------------------------------------
    cur.execute("""
        SELECT l.lecture_id,
               l.name,
               l.day,
               l.start_time,
               l.end_time,
               l.description,
               COALESCE(r.score, 0),
               l.style_profile
        FROM Lecture l
        JOIN Preference p ON p.item_id = l.lecture_id
        LEFT JOIN MBTIRecommendation r
            ON r.item_id = l.lecture_id
            AND (r.mbti=%s OR r.student_id=%s)
        WHERE p.student_id=%s AND p.is_liked=TRUE
    """, (mbti, student, student))

    liked_rows = cur.fetchall()

    liked_courses = []
    for row in liked_rows:
        lec_id, name, day, st, et, desc, mbti_score, style_vec = row
        liked_courses.append({
            "lecture_id": lec_id,
            "name": name,
            "day": day,
            "start": st,
            "end": et,
            "description": desc,
            "score": compute_final_score(mbti_score, style_vec)
        })

    liked_courses.sort(key=lambda x: x["score"], reverse=True)

    cur.close()
    conn.close()

    return render_template(
        "dashboard.html",
        major_by_year=major_by_year,
        minor_filtered=minor_filtered,
        minor_list=minor_list,
        liked_courses=liked_courses
    )

# ---------------------------------------------------------
# LIKE TOGGLE
# ---------------------------------------------------------
@app.post("/toggle-like")
def toggle_like():
    student_id = session["user_id"]
    lecture_id = request.form.get("lecture_id")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT is_liked
        FROM Preference
        WHERE student_id=%s 
          AND item_type='Lecture'
          AND item_id=%s
    """, (student_id, lecture_id))
    row = cur.fetchone()

    if row:
        new_val = not row[0]
        cur.execute("""
            UPDATE Preference
            SET is_liked=%s, updated_at=NOW()
            WHERE student_id=%s AND item_id=%s AND item_type='Lecture'
        """, (new_val, student_id, lecture_id))
    else:
        cur.execute("""
            INSERT INTO Preference (student_id, item_type, item_id, is_liked)
            VALUES (%s, 'Lecture', %s, TRUE)
        """, (student_id, lecture_id))

    conn.commit()
    cur.close()
    conn.close()

    return redirect("/dashboard")

# ---------------------------------------------------------
# TIMETABLE
# ---------------------------------------------------------
def to_time(v):
    return datetime.strptime(str(v), "%H:%M:%S").time()


@app.route("/generate-timetable")
def generate_timetable():
    student = session["user_id"]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT preferred_time FROM student WHERE student_id=%s", (student,))
    preferred_time = cur.fetchone()[0]

    cur.execute("""
        SELECT 
            l.lecture_id,
            l.name,
            l.day,
            l.start_time,
            l.end_time,
            l.room,
            l.description,
            p.name AS professor_name,
            COALESCE(r.score, 0) AS score,
            l.credit
        FROM lecture l
        LEFT JOIN professor p ON p.professor_id = l.professor_id
        LEFT JOIN MBTIRecommendation r
            ON r.item_id = l.lecture_id
           AND (r.student_id=%s OR r.mbti IN 
               (SELECT mbti FROM student WHERE student_id=%s))
        ORDER BY score DESC, l.start_time ASC
    """, (student, student))

    lectures = cur.fetchall()

    cur.close()
    conn.close()



    def match_preferred_time(start, preferred):
        hour = int(str(start).split(":")[0])
        if preferred == "morning":
            return 9 <= hour < 12
        elif preferred == "afternoon":
            return 12 <= hour < 17
        elif preferred == "evening":
            return 17 <= hour < 21
        return True

    weekdays = ["월", "화", "수", "목", "금"]
    timetable = {day: [] for day in weekdays}

    total_credits = 0
    max_credits = 20

    for lec in lectures:
        lec_id, name, day, st, et, room, desc, prof, score, credit = lec

        if day not in timetable:
            continue

        if not match_preferred_time(st, preferred_time):
            continue

        if total_credits + credit > max_credits:
            continue

        def to_minutes(t):
            h, m, s = map(int, str(t).split(":"))
            return h * 60 + m

        st_m = to_minutes(st)
        et_m = to_minutes(et)

        conflict = False
        for existing in timetable[day]:
            if not (et_m <= existing["start"] or st_m >= existing["end"]):
                conflict = True
                break

        if not conflict:
            timetable[day].append({
                "name": name,
                "start": st_m,
                "end": et_m,
                "start_label": str(st),
                "end_label": str(et),
                "professor": prof,
                "room": room,
                "desc": desc,
                "score": score,
                "credit": credit
            })
            total_credits += credit

    return render_template("timetable.html", timetable=timetable)

# ============================================================
# CLUB RECOMMENDATION
# ============================================================
@app.route("/generate-club-recommendation")
def generate_club_recommendation():

    MBTI_CLUB_STYLE = {
        "INTJ": {"학술": 5, "스포츠": 2, "예술": 3},
        "INTP": {"학술": 5, "스포츠": 2, "예술": 3},
        "INFJ": {"학술": 4, "스포츠": 2, "예술": 4},
        "INFP": {"학술": 3, "스포츠": 2, "예술": 5},
        "ISTJ": {"학술": 5, "스포츠": 2, "예술": 2},
        "ISTP": {"학술": 3, "스포츠": 5, "예술": 2},
        "ISFJ": {"학술": 3, "스포츠": 2, "예술": 4},
        "ISFP": {"학술": 2, "스포츠": 3, "예술": 5},

        "ENTJ": {"학술": 4, "스포츠": 4, "예술": 3},
        "ENTP": {"학술": 3, "스포츠": 4, "예술": 4},
        "ENFJ": {"학술": 3, "스포츠": 2, "예술": 5},
        "ENFP": {"학술": 2, "스포츠": 3, "예술": 5},
        "ESTJ": {"학술": 4, "스포츠": 5, "예술": 2},
        "ESTP": {"학술": 2, "스포츠": 5, "예술": 3},
        "ESFJ": {"학술": 2, "스포츠": 3, "예술": 5},
        "ESFP": {"학술": 1, "스포츠": 3, "예술": 5}
    }

    def parse_freq(freq):
        if "주 2회" in freq: return 2
        if "주 1회" in freq: return 1
        if "격주"  in freq: return 1
        return 1

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM ClubRecommendation")
    cur.execute("SELECT club_id, type, activity_frequency FROM club")
    clubs = cur.fetchall()

    for mbti, pref in MBTI_CLUB_STYLE.items():
        for club_id, ctype, freq_text in clubs:

            base = pref.get(ctype, 3)
            freq_value = parse_freq(freq_text)

            raw_score = base * 2 + freq_value
            rating = max(1, min(5, round(raw_score / 3)))

            reason = f"{mbti} → {ctype}, 기본 {base}, 활동빈도 {freq_value}"

            cur.execute("""
                INSERT INTO ClubRecommendation(mbti, club_id, rating, reason)
                VALUES (%s, %s, %s, %s)
            """, (mbti, club_id, rating, reason))

    conn.commit()
    cur.close()
    conn.close()

    return "Club Recommendation 생성 완료!"


# ============================================================
# CLUB PAGE
# ============================================================
# ============================================================
# CLUB PAGE
# ============================================================
@app.route("/club")
def club_page():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    view = request.args.get("view", "all")

    conn = get_connection()
    cur = conn.cursor()

    # 학생 MBTI
    cur.execute("SELECT mbti FROM student WHERE student_id=%s", (user_id,))
    row = cur.fetchone()
    if not row:
        return redirect("/login")
    mbti = row[0]

    # 전체 동아리 + 추천 JOIN
    cur.execute("""
        SELECT c.club_id, c.name, c.type, c.activity_frequency,
               c.max_members, c.current_members, c.description,
               COALESCE(r.rating, 0), r.reason
        FROM club c
        LEFT JOIN ClubRecommendation r
            ON r.club_id=c.club_id AND r.mbti=%s
        ORDER BY r.rating DESC
    """, (mbti,))
    rows = cur.fetchall()

    clubs = [{
        "club_id": r[0],
        "name": r[1],
        "type": r[2],
        "frequency": r[3],
        "max": r[4],
        "current": r[5],
        "description": r[6],
        "rating": r[7],
        "reason": r[8]
    } for r in rows]

    # 찜 목록
    cur.execute("SELECT club_id FROM clubfavorite WHERE student_id=%s", (user_id,))
    liked_clubs = {row[0] for row in cur.fetchall()}

    # ⭐⭐⭐ 지원 목록 (canceled 제외!) ⭐⭐⭐
    cur.execute("""
        SELECT club_id, status 
        FROM clubmembership 
        WHERE student_id=%s
          AND status != 'canceled'
    """, (user_id,))
    applied = {row[0]: row[1] for row in cur.fetchall()}

    cur.close()
    conn.close()

    # TAB FILTER
    if view == "liked":
        clubs = [c for c in clubs if c["club_id"] in liked_clubs]
    elif view == "applied":
        clubs = [c for c in clubs if c["club_id"] in applied]

    return render_template(
        "club.html",
        clubs=clubs,
        liked_clubs=liked_clubs,
        applied=applied,
        view=view
    )


# ============================================================
# 찜하기 / 찜취소
# ============================================================
@app.post("/club/favorite/<int:club_id>")
def club_favorite(club_id):
    user_id = session["user_id"]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT favorite_id 
        FROM clubfavorite
        WHERE student_id=%s AND club_id=%s
    """, (user_id, club_id))
    row = cur.fetchone()

    if row:
        cur.execute("DELETE FROM clubfavorite WHERE favorite_id=%s", (row[0],))
    else:
        cur.execute("""
            INSERT INTO clubfavorite(student_id, club_id)
            VALUES (%s, %s)
        """, (user_id, club_id))

    conn.commit()
    cur.close()
    conn.close()

    return redirect("/club")

# ============================================================
# CLUB APPLY
# ============================================================
@app.post("/club/apply/<int:club_id>")
def club_apply(club_id):
    user_id = session["user_id"]

    conn = get_connection()
    cur = conn.cursor()

    # 1) clubmembership table 업데이트
    cur.execute("""
        INSERT INTO clubmembership (student_id, club_id, status, joined_date)
        VALUES (%s, %s, 'pending', CURRENT_DATE)
        ON CONFLICT (student_id, club_id)
        DO UPDATE SET status='pending', joined_date=CURRENT_DATE
    """, (user_id, club_id))

    # 2) club_log table 에 기록 추가 (리더 대시보드가 참조하는 곳)
    cur.execute("""
        INSERT INTO club_log (club_id, student_id, log_type, status, created_at)
        VALUES (%s, %s, 'application', 'pending', NOW())
    """, (club_id, user_id))

    conn.commit()
    cur.close()
    conn.close()

    return redirect("/club")

# ============================================================
# CLUB CANCEL APPLY
# ============================================================
@app.post("/club/cancel/<int:club_id>")
def club_cancel(club_id):
    user_id = session["user_id"]

    conn = get_connection()
    cur = conn.cursor()

    # 1) clubmembership 상태 변경
    cur.execute("""
        UPDATE clubmembership
        SET status='canceled'
        WHERE student_id=%s AND club_id=%s
    """, (user_id, club_id))

    # 2) club_log 기록도 canceled 로 변경
    cur.execute("""
        UPDATE club_log
        SET status='canceled'
        WHERE club_id=%s AND student_id=%s AND log_type='application'
          AND status='pending'
    """, (club_id, user_id))

    conn.commit()
    cur.close()
    conn.close()

    return redirect("/club")


# ============================================================
# LEADER DASHBOARD
# ============================================================
def club_leader_required(fn):
    def wrapper(*args, **kwargs):
        if "user_type" not in session or session["user_type"] != "leader":
            return redirect("/login")

        leader_id = session["user_id"]
        club_id = session.get("leader_club_id")

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT leader_id FROM club WHERE club_id=%s", (club_id,))
        row = cur.fetchone()

        if not row or row[0] != leader_id:
            conn.close()
            return "Access Denied", 403

        result = fn(*args, **kwargs)
        conn.close()
        return result

    wrapper.__name__ = fn.__name__
    return wrapper

# ============================================================
# LEADER DASHBOARD
# ============================================================
@app.route("/leader-dashboard")
@club_leader_required
def leader_dashboard():

    club_id = session["leader_club_id"]

    conn = get_connection()
    cur = conn.cursor()

    # ------------------------------
    # 클럽 기본 정보
    # ------------------------------
    cur.execute("""
        SELECT club_id, name, type, activity_frequency,
               max_members, current_members, description
        FROM club
        WHERE club_id=%s
    """, (club_id,))
    row = cur.fetchone()

    club = {
        "club_id": row[0],
        "name": row[1],
        "type": row[2],
        "activity_frequency": row[3],
        "max_members": row[4],
        "current_members": row[5],
        "description": row[6]
    }

    # ------------------------------
    # 공지사항
    # ------------------------------
    cur.execute("""
        SELECT log_id, title, content, created_at
        FROM club_log
        WHERE club_id=%s AND log_type='notice'
        ORDER BY created_at DESC
    """, (club_id,))
    notices = [
        {"log_id": n[0], "title": n[1], "content": n[2], "created_at": n[3]}
        for n in cur.fetchall()
    ]

    # ------------------------------
    # 지원자 목록
    # ------------------------------
    cur.execute("""
        SELECT log_id, student_id, status, created_at
        FROM club_log
        WHERE club_id=%s 
          AND log_type='application'
          AND status='pending'
        ORDER BY created_at DESC
    """, (club_id,))

    applicants = [
        {"log_id": a[0], "student_id": a[1], "status": a[2], "created_at": a[3]}
        for a in cur.fetchall()
    ]

    # ------------------------------
    # 활동 기록
    # ------------------------------
    cur.execute("""
        SELECT log_id, title, content, created_at
        FROM club_log
        WHERE club_id=%s AND log_type='activity'
        ORDER BY created_at DESC
    """, (club_id,))
    activities = [
        {"log_id": ac[0], "title": ac[1], "content": ac[2], "created_at": ac[3]}
        for ac in cur.fetchall()
    ]

    # ------------------------------
    # 승인된 멤버 목록
    # ------------------------------
    cur.execute("""
        SELECT m.membership_id, s.student_id, s.name, s.nickname, m.joined_date
        FROM clubmembership m
        JOIN student s ON s.student_id = m.student_id
        WHERE m.club_id=%s AND m.status='approved'
        ORDER BY m.joined_date DESC
    """, (club_id,))
    members = [
        {
            "membership_id": m[0],
            "student_id": m[1],
            "name": m[2],
            "nickname": m[3],
            "joined_date": m[4]
        }
        for m in cur.fetchall()
    ]

    conn.close()

    return render_template(
        "leader_dashboard.html",
        club=club,
        notices=notices,
        applicants=applicants,
        activities=activities,
        members=members
    )

# ============================================================
# ADD NOTICE
# ============================================================
@app.post("/leader/notice/add")
@club_leader_required
def leader_add_notice():

    club_id = session["leader_club_id"]
    title = request.form.get("title")
    content = request.form.get("content")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO club_log (club_id, log_type, title, content)
        VALUES (%s, 'notice', %s, %s)
    """, (club_id, title, content))

    conn.commit()
    conn.close()
    return redirect("/leader-dashboard")


@app.post("/leader/activity/add")
@club_leader_required
def leader_add_activity():

    club_id = session["leader_club_id"]
    title = request.form.get("title")
    content = request.form.get("content")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO club_log (club_id, log_type, title, content, created_at)
        VALUES (%s, 'activity', %s, %s, NOW())
    """, (club_id, title, content))

    conn.commit()
    conn.close()

    return redirect("/leader-dashboard")

# ============================================================
# APPROVE APPLICANT
# ============================================================
@app.post("/leader/apply/approve/<int:log_id>")
@club_leader_required
def leader_approve_applicant(log_id):

    club_id = session["leader_club_id"]

    conn = get_connection()
    cur = conn.cursor()

    # 신청자 정보 가져오기
    cur.execute("""
        SELECT student_id
        FROM club_log
        WHERE log_id=%s AND log_type='application'
    """, (log_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return "지원자 정보를 찾을 수 없습니다.", 400

    student_id = row[0]

    # clubmembership 에 넣기 (이미 존재하면 status만 업데이트)
    cur.execute("""
        INSERT INTO clubmembership (club_id, student_id, status)
        VALUES (%s, %s, 'approved')
        ON CONFLICT (club_id, student_id)
        DO UPDATE SET status='approved';
    """, (club_id, student_id))

    # club_log 상태 변경
    cur.execute("""
        UPDATE club_log
        SET status='approved'
        WHERE log_id=%s
    """, (log_id,))

    # club.current_members +1
    cur.execute("""
        UPDATE club
        SET current_members = current_members + 1
        WHERE club_id=%s
    """, (club_id,))

    conn.commit()
    conn.close()
    return redirect("/leader-dashboard")

# ============================================================
# REJECT APPLICANT
# ============================================================
@app.post("/leader/apply/reject/<int:log_id>")
@club_leader_required
def leader_reject_applicant(log_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE club_log
        SET status='rejected'
        WHERE log_id=%s
    """, (log_id,))

    conn.commit()
    conn.close()
    return redirect("/leader-dashboard")


# ============================================================
# KICK MEMBER
# ============================================================
@app.post("/leader/member/kick/<int:membership_id>")
@club_leader_required
def kick_member(membership_id):

    club_id = session["leader_club_id"]

    conn = get_connection()
    cur = conn.cursor()

    # find student
    cur.execute("""
        SELECT student_id
        FROM clubmembership
        WHERE membership_id=%s AND club_id=%s
    """, (membership_id, club_id))
    row = cur.fetchone()

    if not row:
        conn.close()
        return "해당 멤버가 없습니다.", 400

    # kick
    cur.execute("""
        UPDATE clubmembership
        SET status='kicked'
        WHERE membership_id=%s
    """, (membership_id,))

    # current_members -1
    cur.execute("""
        UPDATE club
        SET current_members = current_members - 1
        WHERE club_id=%s AND current_members > 0
    """, (club_id,))

    conn.commit()
    conn.close()
    return redirect("/leader-dashboard")


# ============================================================
# EDIT CLUB INFO
# ============================================================
@app.post("/leader/club/edit/<int:club_id>")
@club_leader_required
def edit_club(club_id):

    name = request.form.get("name")
    type_ = request.form.get("type")
    freq = request.form.get("activity_frequency")
    max_members = request.form.get("max_members")
    desc = request.form.get("description")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE club
        SET name=%s, type=%s, activity_frequency=%s,
            max_members=%s, description=%s
        WHERE club_id=%s
    """, (name, type_, freq, max_members, desc, club_id))

    conn.commit()
    conn.close()
    return redirect("/leader-dashboard")


# =========================================================
# ACTIVITY RECOMMENDATION
# =========================================================
@app.route("/generate-activity-recommendation")
def generate_activity_recommendation():

    MBTI_ACTIVITY_PREF = {
        "INTJ": {"세미나": 5, "워크숍": 4},
        "INTP": {"세미나": 5, "워크숍": 4},
        "INFJ": {"멘토링": 5, "봉사": 4, "세미나": 3},
        "INFP": {"멘토링": 5, "봉사": 4},
        "ISTJ": {"공모전": 5, "워크숍": 4},
        "ISTP": {"대회": 5, "체험활동": 4},
        "ISFJ": {"봉사": 5, "멘토링": 4},
        "ISFP": {"봉사": 5, "체험활동": 4},
        "ENTJ": {"공모전": 5, "워크숍": 4},
        "ENTP": {"대회": 5, "세미나": 4},
        "ENFJ": {"멘토링": 5, "봉사": 4},
        "ENFP": {"축제": 5, "봉사": 4},
        "ESTJ": {"공모전": 5, "대회": 4},
        "ESTP": {"대회": 5, "체험활동": 4},
        "ESFJ": {"멘토링": 5, "축제": 4},
        "ESFP": {"축제": 5, "체험활동": 4}
    }

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("DELETE FROM activityrecommendation")
        print("🗑 기존 ActivityRecommendation 삭제 완료")

        cur.execute("SELECT activity_id, type FROM activity")
        activities = cur.fetchall()

        print(f" 활동 개수: {len(activities)}")

        insert_count = 0

        for mbti, pref in MBTI_ACTIVITY_PREF.items():
            for act_id, act_type in activities:

                # NULL 또는 공백 제거
                act_type = (act_type or "").strip()

                # 타입 일치하지 않으면 기본값 1
                rating = pref.get(act_type, 1)

                reason = f"{mbti} → '{act_type}' 선호도 {rating}"

                cur.execute("""
                    INSERT INTO activityrecommendation (mbti, activity_id, rating, reason)
                    VALUES (%s, %s, %s, %s)
                """, (mbti, act_id, rating, reason))

                insert_count += 1

        conn.commit()

        print(f"✅ INSERT 완료! 총 {insert_count}개 추가됨.")

        return f"Activity Recommendation 생성 완료! (총 {insert_count}개)"

    except Exception as e:
        conn.rollback()
        print("오류 발생:", e)
        return f"오류 발생: {e}"

    finally:
        cur.close()
        conn.close()

# =========================================================
# ACTIVITY PAGE
# =========================================================
@app.route("/activity")
def activity_page():
    if "user_id" not in session:
        return redirect("/login")

    view = request.args.get("view", "all")
    user_id = session["user_id"]

    conn = get_connection()
    cur = conn.cursor()

    # MBTI
    cur.execute("SELECT mbti FROM student WHERE student_id=%s", (user_id,))
    mbti = cur.fetchone()[0]

    # 전체 활동 + 추천 JOIN
    cur.execute("""
        SELECT 
            a.activity_id, a.name, a.type, a.description,
            a.start_date, a.end_date,
            a.max_participants, a.current_participants,
            COALESCE(r.rating, 0), r.reason
        FROM activity a
        LEFT JOIN activityrecommendation r
            ON r.activity_id = a.activity_id AND r.mbti = %s
        ORDER BY rating DESC
    """, (mbti,))
    activities = cur.fetchall()

    # 찜 목록
    cur.execute("""
        SELECT activity_id
        FROM activityfavorite
        WHERE student_id=%s
    """, (user_id,))
    liked = {row[0] for row in cur.fetchall()}

    # 신청 상태 (canceled 제외 ★)
    cur.execute("""
        SELECT activity_id, status
        FROM activityparticipation
        WHERE student_id=%s
          AND status != 'canceled'
    """, (user_id,))
    applied = {row[0]: row[1] for row in cur.fetchall()}

    cur.close()
    conn.close()

    # VIEW FILTER
    if view == "liked":
        activities = [a for a in activities if a[0] in liked]
    elif view == "applied":
        activities = [a for a in activities if a[0] in applied]

    return render_template(
        "activity.html",
        activities=activities,
        liked=liked,
        applied=applied,
        view=view
    )



@app.post("/activity/favorite/<int:activity_id>")
def activity_favorite(activity_id):
    user_id = session["user_id"]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT favorite_id
        FROM activityfavorite
        WHERE student_id=%s AND activity_id=%s
    """, (user_id, activity_id))
    row = cur.fetchone()

    if row:  # 이미 찜 → 해제
        cur.execute("DELETE FROM activityfavorite WHERE favorite_id=%s", (row[0],))
    else:  # 찜 추가
        cur.execute("""
            INSERT INTO activityfavorite(student_id, activity_id)
            VALUES (%s, %s)
        """, (user_id, activity_id))

    conn.commit()
    cur.close()
    conn.close()

    return redirect("/activity")


@app.post("/activity/apply/<int:activity_id>")
def activity_apply(activity_id):
    user_id = session["user_id"]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO activityparticipation (student_id, activity_id, status, registered_at)
        VALUES (%s, %s, 'pending', NOW())
        ON CONFLICT (student_id, activity_id)
        DO UPDATE SET status='pending', registered_at=NOW();
    """, (user_id, activity_id))

    conn.commit()
    cur.close()
    conn.close()

    return redirect("/activity")


@app.post("/activity/cancel/<int:activity_id>")
def activity_cancel(activity_id):
    user_id = session["user_id"]

    conn = get_connection()
    cur = conn.cursor()

    # 상태만 변경 (삭제 안 함)
    cur.execute("""
        UPDATE activityparticipation
        SET status='canceled'
        WHERE student_id=%s AND activity_id=%s
    """, (user_id, activity_id))

    # 승인된 상태였다면 current_participants 감소 처리
    cur.execute("""
        UPDATE activity
        SET current_participants = current_participants - 1
        WHERE activity_id=%s
          AND current_participants > 0
    """, (activity_id,))

    conn.commit()
    cur.close()
    conn.close()

    return redirect("/activity")




# =========================================================
# STAFF PAGE — STAFF HOME
# =========================================================
@app.route("/staff/home")
def staff_home():
    if "user_type" not in session or session["user_type"] != "staff":
        return redirect("/login")

    staff_id = session["user_id"]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT activity_id, name, type, start_date, end_date,
               current_participants, max_participants
        FROM activity
        WHERE created_by=%s
        ORDER BY start_date
    """, (staff_id,))
    activities = cur.fetchall()

    conn.close()
    return render_template("staff_home.html",
                           activities=activities,
                           staff_name=session["user_name"])


@app.route("/staff/activity/<int:activity_id>")
def staff_activity_manage(activity_id):
    if "user_type" not in session or session["user_type"] != "staff":
        return redirect("/login")

    keyword = request.args.get("search", "").strip()

    conn = get_connection()
    cur = conn.cursor()

    # 활동 정보
    cur.execute("""
        SELECT activity_id, name, type, description,
               start_date, end_date, max_participants, current_participants
        FROM activity
        WHERE activity_id=%s
    """, (activity_id,))
    activity = cur.fetchone()

    # 참여자 목록
    if keyword:
        cur.execute("""
            SELECT p.participation_id, s.student_id, s.name, s.nickname,
                   p.status, p.registered_at
            FROM activityparticipation p
            JOIN student s ON s.student_id = p.student_id
            WHERE p.activity_id=%s
              AND (s.student_id ILIKE %s OR s.name ILIKE %s OR s.nickname ILIKE %s)
            ORDER BY p.registered_at DESC
        """, (activity_id, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"))
    else:
        cur.execute("""
            SELECT p.participation_id, s.student_id, s.name, s.nickname,
                   p.status, p.registered_at
            FROM activityparticipation p
            JOIN student s ON s.student_id = p.student_id
            WHERE p.activity_id=%s
            ORDER BY p.registered_at DESC
        """, (activity_id,))

    members = cur.fetchall()

    conn.close()

    return render_template("activity_manage.html",
                           activity=activity,
                           members=members,
                           keyword=keyword)



@app.post("/staff/activity/<int:activity_id>/approve/<int:pid>")
def staff_approve(activity_id, pid):
    if "user_type" not in session or session["user_type"] != "staff":
        return redirect("/login")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE activityparticipation
        SET status='accepted'
        WHERE participation_id=%s
    """, (pid,))

    cur.execute("""
        UPDATE activity
        SET current_participants = current_participants + 1
        WHERE activity_id=%s AND current_participants < max_participants
    """, (activity_id,))

    conn.commit()
    conn.close()
    return redirect(f"/staff/activity/{activity_id}")



@app.post("/staff/activity/<int:activity_id>/reject/<int:pid>")
def staff_reject(activity_id, pid):
    if "user_type" not in session or session["user_type"] != "staff":
        return redirect("/login")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE activityparticipation
        SET status='rejected'
        WHERE participation_id=%s
    """ , (pid,))

    conn.commit()
    conn.close()
    return redirect(f"/staff/activity/{activity_id}")


@app.post("/staff/activity/<int:activity_id>/edit")
def edit_activity(activity_id):
    if "user_type" not in session or session["user_type"] != "staff":
        return redirect("/login")

    name = request.form.get("name")
    type_ = request.form.get("type")
    description = request.form.get("description")
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    max_participants = request.form.get("max_participants")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE activity
        SET name=%s, type=%s, description=%s,
            start_date=%s, end_date=%s, max_participants=%s
        WHERE activity_id=%s
    """, (name, type_, description, start_date, end_date, max_participants, activity_id))

    conn.commit()
    conn.close()

    return redirect(f"/staff/activity/{activity_id}")





# =========================================================
# PROFILE PAGE (학생 정보 수정)
# =========================================================
@app.route("/profile", methods=["GET", "POST"])
def profile_page():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    conn = get_connection()
    cur = conn.cursor()

    # POST → 저장하기
    if request.method == "POST":
        nickname = request.form.get("nickname")
        mbti = request.form.get("mbti")
        major_id = request.form.get("major_id")
        year_level = request.form.get("year_level")
        preferred_time = request.form.get("preferred_time")

        cur.execute("""
            UPDATE Student
            SET nickname=%s,
                mbti=%s,
                major_id=%s,
                year_level=%s,
                 preferred_time=%s,
                updated_at=NOW()
               
            WHERE student_id=%s
        """, (nickname, mbti, major_id, year_level, preferred_time,user_id))

        conn.commit()
        cur.close()
        conn.close()
        return redirect("/profile")

    # GET → 사용자 정보 가져오기
    cur.execute("""
        SELECT nickname, mbti, major_id, year_level
        FROM Student
        WHERE student_id=%s
    """, (user_id,))
    nickname, mbti, major_id, year_level = cur.fetchone()

    # Major 목록 가져오기
    cur.execute("SELECT major_id, major_name FROM Major ORDER BY major_name")
    major_list = cur.fetchall()

    cur.close()
    conn.close()

    mbti_list = [
        "INTJ","INTP","INFJ","INFP",
        "ISTJ","ISTP","ISFJ","ISFP",
        "ENTJ","ENTP","ENFJ","ENFP",
        "ESTJ","ESTP","ESFJ","ESFP"
    ]

    year_list = [1, 2, 3, 4]

    return render_template(
        "profile.html",
        nickname=nickname,
        mbti=mbti,
        major_id=major_id,
        year_level=year_level,
        major_list=major_list,
        year_list=year_list,
        mbti_list=mbti_list
    )




# =========================================================
# LOGOUT
# =========================================================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# =========================================================
#  FLASK RUN
# =========================================================
if __name__ == "__main__":
    app.run(debug=True)
