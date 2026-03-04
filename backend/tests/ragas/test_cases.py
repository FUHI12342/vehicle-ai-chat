"""
10種問診テストケース定義

車両: ホンダ アコード 2011年式 (vehicle_id: 30TA06210_web)
各テストケースは、症状テキスト・期待urgency・期待action・ground_truthを含む。
RAGAS評価およびE2Eチャットテストの両方で使用する。
"""

VEHICLE_ID = "30TA06210_web"
VEHICLE_MAKE = "ホンダ"
VEHICLE_MODEL = "アコード"
VEHICLE_YEAR = 2011

TEST_CASES = [
    {
        "id": 1,
        "category": "ブレーキ故障",
        "symptom": "ブレーキを踏んでも止まらない感じがする",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "critical",
        "expected_action": "escalate",
        "ground_truth": (
            "ブレーキの効きが悪い場合は即座に安全な場所に停車してください。"
            "絶対に走行を続けないでください。ロードサービスを呼び、"
            "レッカーでディーラーまたは整備工場へ搬送してもらってください。"
            "ブレーキフルードの漏れやブレーキパッドの極端な摩耗が原因の可能性があります。"
        ),
    },
    {
        "id": 2,
        "category": "エンジン警告灯",
        "symptom": "エンジンの警告灯が点灯している",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "high",
        "expected_action": "ask_question",
        "ground_truth": (
            "エンジン警告灯（チェックエンジンランプ）が点灯した場合、"
            "まず警告灯の色（黄色/赤）と点灯パターン（点灯/点滅）を確認してください。"
            "赤色や点滅の場合は直ちに停車が必要です。黄色の点灯であれば、"
            "早めにディーラーでの診断を推奨します。OBD-IIでエラーコードを読み取ることで原因を特定できます。"
        ),
    },
    {
        "id": 3,
        "category": "走行中異音",
        "symptom": "走行中にガタガタと異音がする",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "medium",
        "expected_action": "ask_question",
        "ground_truth": (
            "走行中の異音は発生する速度域、場所（前輪/後輪/足回り/エンジンルーム）、"
            "状況（直進時/旋回時/段差通過時）によって原因が異なります。"
            "サスペンション、ハブベアリング、ドライブシャフト、排気系統などの点検が必要です。"
            "速度や場所を特定する追加質問が重要です。"
        ),
    },
    {
        "id": 4,
        "category": "エアコン不調",
        "symptom": "エアコンから冷たい風が出ない",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "low",
        "expected_action": "ask_question",
        "ground_truth": (
            "エアコンから冷風が出ない場合、まずA/Cボタンがオンになっているか、"
            "温度設定が適切か確認してください。設定に問題がなければ、"
            "冷媒（エアコンガス）の不足が最も一般的な原因です。"
            "コンプレッサーの故障やエアコンフィルターの詰まりも考えられます。"
        ),
    },
    {
        "id": 5,
        "category": "エンジン始動不良",
        "symptom": "エンジンがかからない",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "high",
        "expected_action": "ask_question",
        "ground_truth": (
            "エンジンがかからない場合、まずキーを回した時の反応を確認してください。"
            "セルモーターが回らない場合はバッテリー上がりの可能性が高いです。"
            "セルは回るがエンジンがかからない場合は燃料系統やスパークプラグの問題が考えられます。"
            "バッテリーの電圧確認、スターターモーターの動作確認が初期診断のポイントです。"
        ),
    },
    {
        "id": 6,
        "category": "オイル漏れ",
        "symptom": "駐車場の地面に油のシミがある",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "high",
        "expected_action": "ask_question",
        "ground_truth": (
            "駐車場所に油のシミがある場合、まず液体の色を確認してください。"
            "黒〜茶色はエンジンオイル、赤色はATF（オートマオイル）、"
            "緑色は冷却水、透明はエアコンの排水（正常）の可能性があります。"
            "漏れ位置（エンジン下部/ミッション付近）と量も重要な判断材料です。"
            "オイル漏れを放置するとエンジン焼き付きの原因になります。"
        ),
    },
    {
        "id": 7,
        "category": "タイヤ空気圧",
        "symptom": "タイヤの空気圧警告灯がついた",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "medium",
        "expected_action": "ask_question",
        "ground_truth": (
            "タイヤ空気圧警告灯（TPMS）が点灯した場合、いずれかのタイヤの空気圧が"
            "規定値を下回っています。まず目視でタイヤのパンクや極端な空気圧低下がないか確認してください。"
            "ガソリンスタンドなどで空気圧を規定値に調整してください。"
            "規定空気圧は運転席ドアの内側のラベルに記載されています。"
            "補充後もすぐに再点灯する場合はパンクの可能性があります。"
        ),
    },
    {
        "id": 8,
        "category": "ハンドル重い",
        "symptom": "ハンドルが急に重くなった",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "medium",
        "expected_action": "ask_question",
        "ground_truth": (
            "ハンドルが急に重くなった場合、パワーステアリング系統の異常が考えられます。"
            "油圧式の場合はパワステフルードの漏れや不足、パワステポンプの故障が原因です。"
            "電動式の場合はEPS（電動パワーステアリング）モーターやセンサーの故障が考えられます。"
            "パワステ警告灯が点灯していないかも確認してください。"
            "走行は可能ですが、操舵に大きな力が必要になるため注意が必要です。"
        ),
    },
    {
        "id": 9,
        "category": "仕様確認系",
        "symptom": "停車中にエンジンが止まることがある",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "low",
        "expected_action": "spec_answer",
        "ground_truth": (
            "ホンダ アコードにはアイドリングストップ機能が搭載されている場合があります。"
            "信号待ちなどの停車中にエンジンが自動的に停止し、ブレーキを離すと再始動します。"
            "これは燃費向上のための正常な動作です。"
            "アイドリングストップをオフにしたい場合はダッシュボードのボタンで無効化できます。"
        ),
    },
    {
        "id": 10,
        "category": "オーバーヒート",
        "symptom": "水温計が赤いところまで上がっている",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "critical",
        "expected_action": "escalate",
        "ground_truth": (
            "水温計が赤い領域（H）に達している場合、エンジンがオーバーヒートしています。"
            "直ちに安全な場所に停車し、エンジンを停止してください。"
            "絶対にラジエーターキャップを開けないでください（高温の蒸気で火傷の危険）。"
            "冷却水の漏れ、ラジエーターファンの故障、サーモスタットの固着、"
            "ウォーターポンプの故障などが原因として考えられます。"
            "ロードサービスでの搬送を推奨します。"
        ),
    },
]
