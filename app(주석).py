from datetime import datetime, date 
import json ## 파일에 있는 글자들을 파이썬이 받을 수 있는 리스트와 딕셔너리로 변환하는 도구
import os ## 윈도우와 소통하는 도구(파일 찾기, api키 찾기)
import re ## 긴 글자 속 원하는 특징만 뽑아내는 도구
from flask import Flask, jsonify, render_template, request ## 앱을 띄워주는 장치
from google import genai  # Google GenAI 공식 SDK ## 구글 ai 불러오기
from dotenv import load_dotenv ## api키 숨기기 env에 자기 키 넣으면 ai 작동

load_dotenv() ## env 파일 불러오기
app = Flask(__name__) ## 백엔드 서버

# 데이터가 저장될 파일 이름
DB_FILE = "database.json"

# Gemini 클라이언트 초기화
client = genai.Client(api_key=os.getenv("GCP_API_KEY"))


def load_database():
  if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
      try:
        data = json.load(f)
        # 데이터를 불러올 때 오늘 날짜를 기준으로 남은 일수(remaining_days)를 실시간 갱신
        update_remaining_days(data)
        return data
      except json.JSONDecodeError:
        pass
  return {
      "InFridge": [],
      "InFreezer": [],
      "InCabinet": [],
  }
## DB_FILE 읽기 모드로 열고 data 변수에다가 json(리스트 딕셔너리 형태)으로 저장하고 
## 세번째 함수 update_remaining_days에 넣어서 날짜 최신화한다
## return 쪽을 잘 모르겠는데 최신화까지 완료된 데이터를 "InFridge": [], "InFreezer": [], "InCabinet": [],
## 에다가 알맞게 넣는건지 아니면 데이터가 없을 시 저 칸을 만드는 건지

def save_database(data):
  with open(DB_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
## load는 dbfiled의 데이터 불러오기 save는 dbfiled의 데이터 저장하기


# 저장된 아이템들의 만료일(expiry_date)을 기준으로 오늘 날짜와 비교해 남은 일수(remaining_days)를 갱신하는 함수
def update_remaining_days(data):
  today = date.today()
  for category in ["InFridge", "InFreezer", "InCabinet"]:
    for item in data.get(category, []):
      if "expiry_date" in item:
        exp_date = datetime.strptime(item["expiry_date"], "%Y-%m-%d").date()
        # 남은 일수 계산 (만료일 - 오늘)
        delta = (exp_date - today).days
        item["remaining_days"] = delta

        # 남은 일수에 따라 상태(status) 자동 갱신
        if delta < 0:
          item["status"] = "danger"  # 만료됨
        elif delta <= 7:
          item["status"] = "warning"  # 임박
        else:
          item["status"] = "safe"  # 안전
  save_database(data)
## 냉장고에 있는 음식들 만료날짜 계산하기 delta = exp data - todays = remain day 0일 미만 7일 이하 그 외

## load -> remain -> save

# 서버가 시작될 때 데이터 불러오기 및 디데이 갱신
database = load_database()


@app.route("/")
def home():
  return render_template("Fridge_tab.html")
## 회면 띄우기 생략

@app.route("/summary")
def summary_tab():
  all_items = (
      database["InFridge"] + database["InFreezer"] + database["InCabinet"]
  )
  total_count = len(all_items)
  warning_count = sum(
      1 for item in all_items if item.get("status") == "warning"
  )
  danger_count = sum(1 for item in all_items if item.get("status") == "danger")
  safe_count = total_count - warning_count - danger_count

  if total_count > 0:
    safe_pct = (safe_count / total_count) * 100
    warning_pct = safe_pct + (warning_count / total_count) * 100
  else:
    safe_pct = 0
    warning_pct = 0

  alert_items = [
      item for item in all_items if item.get("status") in ["warning", "danger"]
  ]

  return render_template(
      "Summay_tab.html",
      total_count=total_count,
      warning_count=warning_count,
      danger_count=danger_count,
      safe_pct=safe_pct,
      warning_pct=warning_pct,
      alert_items=alert_items,
  )
## 원형 그래프 띄우기 생략

@app.route("/recipes")
def recipes_tab():
  return render_template("Recipes_tab.html")


@app.route("/InFirdge.html")
def in_fridge():
  return render_template("InFirdge.html", items=database["InFridge"])


@app.route("/InFreezer.html")
def in_freezer():
  return render_template("InFreezer.html", items=database["InFreezer"])


@app.route("/InCabinet.html")
def in_cabinet():
  return render_template("InCabinet.html", items=database["InCabinet"])


# --- [AI 기반 레시피 추천 API] ---
@app.route("/api/recommend-recipes", methods=["GET"])
def recommend_recipes():
  all_items = (
      database.get("InFridge", [])
      + database.get("InFreezer", [])
      + database.get("InCabinet", []) ## all items에 모든 음식 재료들  저장
  )
  ingredient_names = [
      item["name"] for item in all_items if item.get("name") # 음식 재료들 이름으로만 저장
  ]

  if not ingredient_names:
    return jsonify({
        "success": True,
        "recipes": [],
        "message": "등록된 식재료가 없습니다.", ## 재료가 없으면 등록된 식재료가 없습니다가 나오게함
    })

  prompt = f"""
    현재 냉장고에 있는 재료 목록: {', '.join(ingredient_names)}

    위 재료들을 활용해서 만들 수 있는 최적의 요리 3가지를 추천해줘.
    반드시 아래와 같은 Strict JSON 형식 배열로만 답변해줘. 설명이나 줄바꿈 텍스트는 빼고 오직 JSON만 반환해줘.

    [
      {{
        "title": "요리 이름",
        "match_rate": "95%",
        "ingredients": ["사용한 재료1", "사용한 재료2"],
        "search_query": "유튜브 검색어 (예: 김치볶음밥 레시피)"
      }}
    ]
    """
  ## 제미나이에게 들어가는 프롬포트

  try:
    response = client.models.generate_content(
        model="gemini-3.5-flash", contents=prompt
    )
    res_text = response.text.strip() ## 답변 앞뒤에 이상한거 붙은거 벗김

    # JSON 형식이 아닌 마크다운 텍스트 처리
    if res_text.startswith("```json"):
      res_text = res_text.replace("```json", "").replace("```", "").strip()

    recipes = json.loads(res_text)
  except Exception as e:
    print(f"[AI 레시피 추천 에러]: {e}")
    # 기본 예시 레시피
    recipes = [{
        "title": f"{ingredient_names[0]} 활용 요리",
        "match_rate": "80%",
        "ingredients": ingredient_names[:3],
        "search_query": f"{ingredient_names[0]} 레시피",
    }]

  return jsonify({"success": True, "recipes": recipes})


# 1. 식품 추가 및 AI 소비기한 산정 API
@app.route("/api/add-ingredient", methods=["POST"])
def add_ingredient():
  data = request.json
  name = data.get("name")
  storage = data.get("storage")  # '냉장', '냉동', '상온'
## data에 이름과 저장칸으로 데이터 저장
  # 기본값 설정 (AI 연동 실패 대비)
  remaining_days = 7

  # AI(Gemini)를 통한 소비기한 자동 산정 로직
  try:
    prompt = (
        f"식품 이름: {name}, 보관 방법: {storage}. 대한민국 식약처(MFDS) "
        "식품별 권장 소비기한 자료를 근거로, 이 식품의 해당 보관 방법에서의 "
        "남은 유통기한(소비기한)을 오직 일(day) 단위 숫자만 알려줘. 예시: 14"
    )
    
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite", 
        contents=prompt
    )
    ## 프롬포트
    
    # [핵심] 응답 텍스트에서 숫자만 안전하게 추출 (예: "약 14일" -> 14)
    response_text = response.text.strip()
    digits = "".join(filter(str.isdigit, response_text))
    
    if digits:
      remaining_days = int(digits)
    else:
      print(f"[디버깅] AI가 숫자를 반환하지 않음. 응답 내용: {response_text}")

  except Exception as e:
    # API 호출 실패 시 터미널에 정확한 에러 원인 출력
    print(f"[에러 발생] AI 연동 중 오류가 발생했습니다: {e}")
    remaining_days = 7

  # 오늘 날짜를 기준으로 만료일(expiry_date) 계산
  from datetime import timedelta
  today = date.today()
  expiry_date = today + timedelta(days=remaining_days)

  category_map = {"냉장": "InFridge", "냉동": "InFreezer", "상온": "InCabinet"}
  target_category = category_map.get(storage, "InFridge") ## 요부분은 어디서 쓰이는건지 모르겠음 설명으론 한글을 영어로 바꿔준다는데

  # 상태 분류
  if remaining_days < 0:
    status = "danger"
  elif remaining_days <= 7:
    status = "warning"
  else:
    status = "safe"

  new_item = {
      "name": name,
      "remaining_days": remaining_days,
      "expiry_date": expiry_date.strftime("%Y-%m-%d"),
      "status": status,
  }

  database[target_category].append(new_item)
  save_database(database) ## 덮어씌우기

  return jsonify({
      "success": True,
      "category": target_category,
      "message": f"{target_category}에 {name}(D-{remaining_days}) 등록됨", ##완료 신호
  })


@app.route("/api/delete-ingredient", methods=["POST"])
def delete_ingredient():
  data = request.json
  storage = data.get("storage")
  index = data.get("index")

  if storage in database and 0 <= index < len(database[storage]): ## 오류방지 지우고 싶은 번호(index)가 0과 총 저장갯수 사이에서만 작동하게 해줌
    deleted_item = database[storage].pop(index)
    save_database(database)
    return jsonify({
        "success": True,
        "message": f"{deleted_item['name']} 삭제 완료!",
    })
## 삭제 처리 후 완료 메세지
  return jsonify({"success": False, "message": "삭제 실패"})


if __name__ == "__main__":
  app.run(debug=True)