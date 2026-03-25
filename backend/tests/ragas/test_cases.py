"""
21種問診テストケース定義

車両: ホンダ アコード 2011年式 (vehicle_id: 30TA06210_web)
各テストケースは、症状テキスト・期待urgency・期待action・ground_truthを含む。
RAGAS評価およびE2Eチャットテストの両方で使用する。

ID 1-10: 初期テストケース
ID 11-18: キーワード緊急度ルールカバー漏れ補完
ID 19-21: 追加ケース（セレクトレバー、ブレーキ異音、エンジン始動不良バリエーション）

v3.0: ground_truthをオーナーズマニュアル(30TA06210_web.pdf)の実際の記載内容から再作成。
      手順ありケースにはmanual_stepsを追加。
v4.0: max_expected_turns, expected_final_action, expected_coverage, forbidden_terms を追加。
      not_coveredケースの期待動作を明確化。
v5.0: ID 19-21 を追加。
v5.1: expected_coverageを実態に合わせて修正。
      マニュアルに関連情報があるが直接的な手順がないケースは partially_covered に変更。
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
        "expected_coverage": "covered",
        "max_expected_turns": 4,
        "expected_final_action": "escalate",
        "ground_truth": (
            "マニュアルP.153「フットブレーキ」: ブレーキの効きが悪いと感じたときは"
            "Honda販売店で点検を受けてください。"
            "P.214「ブレーキ警告灯が点灯したとき」: ブレーキ液がMINより下の場合は"
            "走行せずHonda販売店に連絡してください。ブレーキ液がMIN以上の場合は"
            "ブレーキペダルを強く踏み、ペダルがスポンジのように柔らかい場合は"
            "走行せずHonda販売店に連絡してください。"
            "P.51: ブレーキ警告灯が走行中に点灯した場合、ブレーキ液量が低下しています。"
            "ただちにHonda販売店で点検を受けてください。"
            "ABS警告灯と同時に点灯した場合は、ブレーキの制動が不安定になる"
            "可能性があるため、Honda販売店に連絡してください。"
        ),
        "manual_steps": [
            "安全な場所に停車する",
            "ブレーキ液のリザーバータンクの液面を確認する（MINラインより上か下か）",
            "ブレーキペダルを強く踏み、ペダルの感触を確認する（硬い/スポンジのように柔らかい）",
            "液面がMIN以下またはペダルが柔らかい場合は走行せずHonda販売店に連絡する",
        ],
    },
    {
        "id": 2,
        "category": "エンジン警告灯",
        "symptom": "エンジンの警告灯が点灯している",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "high",
        "expected_action": "ask_question",
        "expected_coverage": "covered",
        "max_expected_turns": 5,
        "expected_final_action": "provide_answer",
        "ground_truth": (
            "マニュアルP.51「PGM-FI警告灯」: エンジンやオートマチックトランスミッションの"
            "排気ガス制御システムに関連する警告灯です。"
            "走行中に点灯した場合はHonda販売店で点検を受けてください。"
            "P.214「PGM-FI警告灯が点灯したとき」: 点灯の場合は高速走行を避け、"
            "Honda販売店で点検を受けてください。"
            "点滅の場合は50km/h以下で走行し、Honda販売店で点検を受けてください。"
        ),
    },
    {
        "id": 3,
        "category": "走行中異音",
        "symptom": "走行中にガタガタと異音がする",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "medium",
        "expected_action": "ask_question",
        "expected_coverage": "partially_covered",  # ブレーキ異音(P.153)、ABS音(P.154)の関連記載あり
        "max_expected_turns": 2,
        "expected_final_action": "escalate",
        "forbidden_terms": ["サスペンション交換", "ドライブシャフト"],
        "ground_truth": (
            "マニュアルに走行中の一般的な異音に関する該当記載なし。"
            "P.153にブレーキを踏んだ時に異音がする場合はHonda販売店で点検との記載あり。"
            "P.154にABS作動時のブレーキペダルの振動や音は正常との記載あり。"
            "走行中の異音全般についてはマニュアルに記載がないため、"
            "Honda販売店での点検を推奨します。"
        ),
    },
    {
        "id": 4,
        "category": "エアコン不調",
        "symptom": "エアコンから冷たい風が出ない",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "low",
        "expected_action": "ask_question",
        "expected_coverage": "partially_covered",  # エアコン操作ページあり、故障TSなし
        "max_expected_turns": 2,
        "expected_final_action": "escalate",
        "forbidden_terms": ["冷媒ガス補充", "コンプレッサー交換"],
        "ground_truth": (
            "マニュアルにエアコンの故障・不調に関する該当記載なし。"
            "マニュアルにはエアコンの操作方法（温度設定、風量、内気循環/外気導入の"
            "切り替え方法）の記載はあるが、冷風が出ない場合のトラブルシューティングは"
            "記載されていません。Honda販売店での点検を推奨します。"
        ),
    },
    {
        "id": 5,
        "category": "エンジン始動不良",
        "symptom": "エンジンがかからない",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "high",
        "expected_action": "ask_question",
        "expected_coverage": "covered",
        "max_expected_turns": 8,
        "expected_final_action": "provide_answer",
        "ground_truth": (
            "マニュアルP.206「エンジンが始動しないとき」: "
            "スターターが回らない場合はバッテリー上がりの可能性があります。"
            "ジャンプスタートの手順はP.208を参照してください。"
            "スターターが回る場合は、エンジンの始動手順（P.141）を再度確認してください。"
            "イモビライザーシステムの異常で始動できない場合もあります（P.89参照）。"
            "燃料が十分にあるか確認してください（燃料計 P.62）。"
            "ヒューズの点検と交換はP.218を参照。"
            "P.141: エンジンの始動手順 - パーキングブレーキがかかっていることを確認し、"
            "セレクトレバーがPにあることを確認し、ブレーキペダルを踏みながら"
            "エンジンスイッチを押してください。"
        ),
        "manual_steps": [
            "スターターが回るか確認する",
            "スターターが回らない場合: バッテリー上がりの可能性→ジャンプスタート（P.208）を試す",
            "スターターが回る場合: エンジンの始動手順を再確認する",
            "パーキングブレーキがかかっていることを確認する",
            "セレクトレバーがPにあることを確認する",
            "ブレーキペダルを踏みながらエンジンスイッチを押す",
            "イモビライザーシステムの異常がないか確認する（P.89参照）",
            "燃料が十分にあるか確認する（燃料計 P.62参照）",
            "ヒューズを点検する（P.218参照）",
        ],
        "user_response_overrides": {
            "かかりますか": "いいえ、かかりません",
            "始動しますか": "いいえ、始動しません",
        },
    },
    {
        "id": 6,
        "category": "オイル漏れ",
        "symptom": "駐車場の地面に油のシミがある",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "high",
        "expected_action": "escalate",
        "expected_coverage": "partially_covered",  # 油圧警告灯(P.213)の関連記載あり
        "max_expected_turns": 3,
        "expected_final_action": "escalate",
        "ground_truth": (
            "マニュアルに「地面の油のシミ」に関する直接的な記載はない。"
            "油圧警告灯の手順（P.213）は警告灯点灯時の対処であり、"
            "地面の油シミとは異なるシナリオ。"
            "マニュアルに記載のない症状のため、Honda販売店での点検を案内する。"
        ),
        "manual_steps": [
            "マニュアルに該当する記載がないことを伝える",
            "Honda販売店またはディーラーでの点検を案内する",
        ],
    },
    {
        "id": 7,
        "category": "タイヤ空気圧",
        "symptom": "タイヤの空気圧警告灯がついた",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "medium",
        "expected_action": "ask_question",
        "expected_coverage": "partially_covered",  # パンクしたとき(P.200)の関連記載あり
        "max_expected_turns": 2,
        "expected_final_action": "escalate",
        "forbidden_terms": ["空気圧の数値", "TPMS", "リセット"],
        "ground_truth": (
            "マニュアルにタイヤ空気圧警告灯（TPMS）の記載なし。"
            "2011年式ホンダ アコード（日本仕様）のオーナーズマニュアルには"
            "タイヤ空気圧監視システム（TPMS）の警告灯に関する記載がありません。"
            "タイヤに関する一般的な情報（パンクしたとき P.200）はあるが、"
            "空気圧警告灯の該当記載はないため、Honda販売店での点検を推奨します。"
        ),
    },
    {
        "id": 8,
        "category": "ハンドル重い",
        "symptom": "ハンドルが急に重くなった",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "medium",
        "expected_action": "ask_question",
        "expected_coverage": "partially_covered",  # VSA警告灯(P.54)の関連記載あり
        "max_expected_turns": 2,
        "expected_final_action": "escalate",
        "forbidden_terms": ["パワステオイル補充", "EPS修理"],
        "ground_truth": (
            "マニュアルにパワーステアリングの故障・不調に関する該当記載なし。"
            "P.54にVSA（ビークルスタビリティアシスト）警告灯の記載はあるが、"
            "パワーステアリング警告灯やEPS警告灯の記載はありません。"
            "ハンドルが急に重くなる症状についてはマニュアルに記載がないため、"
            "Honda販売店での点検を推奨します。"
        ),
    },
    {
        "id": 9,
        "category": "仕様確認系",
        "symptom": "停車中にエンジンが止まることがある",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "low",
        "expected_action": "escalate",  # マニュアル記載なし → ディーラー誘導
        "expected_coverage": "partially_covered",  # エンジン関連記載が広く存在
        "max_expected_turns": 2,
        "expected_final_action": "escalate",
        "forbidden_terms": ["アイドリングストップ機能", "ECUリセット"],
        "ground_truth": (
            "マニュアルにアイドリングストップ機能の記載なし。"
            "2011年式ホンダ アコード（日本仕様）のオーナーズマニュアルには"
            "アイドリングストップ機能に関する記載がありません。"
            "停車中にエンジンが止まる症状は正常な仕様ではない可能性があります。"
            "エンジンの不調やアイドリング不安定が考えられるため、"
            "Honda販売店での点検を推奨します。"
        ),
    },
    {
        "id": 10,
        "category": "オーバーヒート",
        "symptom": "水温計が赤いところまで上がっている",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "critical",
        "expected_action": "escalate",
        "expected_coverage": "covered",
        "max_expected_turns": 9,
        "expected_final_action": "escalate",
        "ground_truth": (
            "マニュアルP.62「水温計」: 水温計がH（高温）のマークを示した場合、"
            "エンジンがオーバーヒートしています。安全な場所に停車してください（P.211参照）。"
            "P.211-212「オーバーヒートしたとき」: "
            "安全な場所に停車し、セレクトレバーをPに入れ、パーキングブレーキをかけ、"
            "非常点滅表示灯を点灯させてください。"
            "蒸気が出ていない場合はエンジンを切りボンネットを開けてください。"
            "蒸気が出ている場合はエンジンを止め、蒸気が出なくなってからボンネットを開けてください。"
            "冷却ファンが回っているか確認し、冷却水量を確認してください。"
            "リザーバータンクの冷却水が不足していれば補給してください。"
            "エンジンが冷えたら再始動し、Honda販売店へ向かってください。"
            "警告: ラジエーターキャップは絶対に外さないでください。"
        ),
        "manual_steps": [
            "安全な場所に停車する",
            "セレクトレバーをPに入れ、パーキングブレーキをかける",
            "非常点滅表示灯を点灯させる",
            "蒸気が出ているか確認する",
            "蒸気なし: エンジンを切りボンネットを開ける / 蒸気あり: エンジンを止め蒸気が止まるまで待つ",
            "冷却ファンが回っているか確認する",
            "冷却水量を確認する（リザーバータンク）",
            "冷却水が不足していれば補給する",
            "エンジンが冷えたら再始動しHonda販売店へ向かう",
        ],
    },
    # --- ID 11-18: キーワード緊急度ルール カバー漏れ補完 ---
    {
        "id": 11,
        "category": "煙の発生",
        "symptom": "ボンネットから白い煙が出ている",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "critical",
        "expected_action": "escalate",
        "expected_coverage": "covered",
        "max_expected_turns": 3,
        "expected_final_action": "escalate",
        "ground_truth": (
            "マニュアルP.211「オーバーヒートしたとき」: "
            "ボンネットから蒸気が出ている場合はオーバーヒートの兆候です。"
            "エンジンを止め、蒸気が出なくなるまで待ってからボンネットを開けてください。"
            "ラジエーターキャップは絶対に外さないでください。"
            "冷却水量を確認し、不足していれば補給してください。"
            "Honda販売店での点検を受けてください。"
        ),
    },
    {
        "id": 12,
        "category": "火災兆候",
        "symptom": "エンジンルームから火が見える",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "critical",
        "expected_action": "escalate",
        "expected_coverage": "not_covered",
        "max_expected_turns": 1,
        "expected_final_action": "escalate",
        "forbidden_terms": ["消火器", "消火手順"],
        "ground_truth": (
            "マニュアルにエンジンルームからの火災に関する該当記載なし。"
            "車両火災に関するトラブルシューティングはオーナーズマニュアルには"
            "記載されていません。直ちに安全な場所に停車し、全員が車外に避難し、"
            "119番通報してください。マニュアルに記載のない緊急事態のため、"
            "Honda販売店に連絡してください。"
        ),
    },
    {
        "id": 13,
        "category": "冷却水漏れ",
        "symptom": "冷却水が減っている気がする",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "critical",
        "expected_action": "escalate",
        "expected_coverage": "covered",
        "max_expected_turns": 6,
        "expected_final_action": "escalate",
        "ground_truth": (
            "マニュアルP.211-212「オーバーヒートしたとき」: "
            "冷却水量の確認手順が記載されています。リザーバータンクの液面を確認し、"
            "不足している場合は補給してください。"
            "P.62: 水温計がH（高温）のマークに達した場合はオーバーヒートです。"
            "冷却水が不足したまま走行するとオーバーヒートの原因となります。"
            "ラジエーターキャップは絶対に外さないでください。"
            "Honda販売店で漏れ箇所の点検を受けてください。"
        ),
        "manual_steps": [
            "安全な場所に停車する",
            "エンジンが十分に冷えるまで待つ",
            "リザーバータンクの冷却水量を確認する",
            "冷却水が不足していれば補給する",
            "ラジエーターキャップは外さない",
            "Honda販売店で漏れ箇所の点検を受ける",
        ],
    },
    {
        "id": 14,
        "category": "走行中振動",
        "symptom": "走行中にブルブル振動する",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "high",
        "expected_action": "ask_question",
        "expected_coverage": "partially_covered",  # ABS振動(P.154)、タイヤ関連記載あり
        "max_expected_turns": 2,
        "expected_final_action": "escalate",
        "forbidden_terms": ["ホイールバランス調整", "アライメント"],
        "ground_truth": (
            "マニュアルに走行中の振動に関する該当記載なし。"
            "P.154にABS作動時のブレーキペダルの振動や音は正常な動作との記載あり。"
            "走行中の一般的な振動についてはマニュアルに記載がないため、"
            "Honda販売店での点検を推奨します。"
        ),
    },
    {
        "id": 15,
        "category": "異臭",
        "symptom": "ゴム焦げた臭いがする",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "high",
        "expected_action": "ask_question",
        "expected_coverage": "partially_covered",  # エンジン/ベルト関連記載が間接的にヒット
        "max_expected_turns": 2,
        "expected_final_action": "escalate",
        "forbidden_terms": ["ベルト交換", "クラッチ交換"],
        "ground_truth": (
            "マニュアルに異臭に関する該当記載なし。"
            "ゴムが焦げた臭いに関するトラブルシューティングは"
            "オーナーズマニュアルには記載されていません。"
            "マニュアルに記載のない症状のため、Honda販売店での点検を推奨します。"
        ),
    },
    {
        "id": 16,
        "category": "ABS警告灯",
        "symptom": "ABSランプが点灯している",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "high",
        "expected_action": "ask_question",
        "expected_coverage": "covered",
        "max_expected_turns": 4,
        "expected_final_action": "provide_answer",
        "ground_truth": (
            "マニュアルP.53「ABS（アンチロックブレーキシステム）警告灯」: "
            "常時点灯、あるいは全く点灯しない場合は、ただちにHonda販売店で"
            "点検を受けてください（P.154参照）。"
            "P.154「ABS」: ABS警告灯が点灯した場合はHonda販売店で点検を受けてください。"
            "ABSが作動しているとき（急ブレーキ時）にブレーキペダルに振動を感じたり"
            "音がすることがありますが、これは正常な動作です。"
            "なお、ABS警告灯が点灯している場合でも通常のブレーキは機能しますが、"
            "ABSの制御は行われません。"
        ),
    },
    {
        "id": 17,
        "category": "燃費悪化",
        "symptom": "最近ガソリンの減りが早い",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "medium",
        "expected_action": "ask_question",
        "expected_coverage": "partially_covered",  # 燃料残量警告灯(P.53)の関連記載あり
        "max_expected_turns": 2,
        "expected_final_action": "escalate",
        "forbidden_terms": ["燃料フィルター交換", "インジェクター洗浄"],
        "ground_truth": (
            "マニュアルに燃費悪化に関する該当記載なし。"
            "P.53に燃料残量警告灯の記載あり（点灯したら早めに給油してください。"
            "点滅したときはHonda販売店で点検を受けてください）。"
            "燃費悪化のトラブルシューティングはオーナーズマニュアルには"
            "記載されていません。Honda販売店での点検を推奨します。"
        ),
    },
    {
        "id": 18,
        "category": "ワイパー故障",
        "symptom": "ワイパーが動かない",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "medium",
        "expected_action": "ask_question",
        "expected_coverage": "covered",
        "max_expected_turns": 5,
        "expected_final_action": "provide_answer",
        "ground_truth": (
            "マニュアルP.100「ワイパー/ウォッシャー」: ワイパースイッチの操作方法"
            "（OFF/LO/HI/AUTO/MIST）が記載されています。"
            "ワイパーが動かない場合の直接的なトラブルシューティングの記載はないが、"
            "P.101にワイパーモーターには保護機能があり、モーターの負担が大きい状態が"
            "続くと一時的に停止するとの記載あり。数分経過すると自動的に復帰します。"
            "P.215-216「ヒューズ」: ワイパーのヒューズ（7.5A）は運転席側の"
            "ヒューズボックスにあります。ヒューズが切れていないか確認してください。"
            "寒冷時、凍結によりワイパーブレードがガラスに張り付くことがあるので、"
            "デフロスターでフロントガラスを温めてからワイパーを作動させてください。"
        ),
        "manual_steps": [
            "ワイパースイッチの設定を確認する（OFF以外になっているか）",
            "ワイパーモーターの保護機能で一時停止していないか数分待つ",
            "運転席側ヒューズボックスのワイパーヒューズ（7.5A）を確認する",
            "ヒューズが切れていれば同じアンペア数のヒューズに交換する",
            "寒冷時はデフロスターでフロントガラスを温めてから再度試す",
        ],
        # シミュレーションユーザー応答制御:
        # 「ワイパーは動きますか？」に「はい」と答えると症状と矛盾するため上書き
        "user_response_overrides": {
            "動きますか": "いいえ、動きません",
            "動作しますか": "いいえ、動きません",
        },
    },
    # ── ID 19-21: 追加ケース ──
    {
        "id": 19,
        "category": "セレクトレバー不動",
        "symptom": "セレクトレバーが動かない",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "medium",
        "expected_action": "ask_question",
        "expected_coverage": "covered",
        "max_expected_turns": 8,
        "expected_final_action": "provide_answer",
        "ground_truth": (
            "マニュアルP.210「セレクトレバーが動かないとき」: "
            "シフトロック解除の手順が記載されている。"
            "1. パーキングブレーキがかかっていることを確認する。"
            "2. エンジンスイッチをオフにする。"
            "3. 内蔵キーを取り出す。"
            "4. マイナスドライバーに布を巻く。"
            "5. シフトロック解除穴のカバーを外す。"
            "6. 内蔵キーを解除穴に差し込み、押しながらセレクトレバーのボタンを押して操作する。"
            "P.143: セレクトレバーの操作方法。ブレーキペダルを踏みながら操作する。"
        ),
        "manual_steps": [
            "パーキングブレーキがかかっていることを確認する",
            "ブレーキペダルを踏みながらセレクトレバーを操作してみる",
            "エンジンがかかっているか確認する",
            "改善しない場合: エンジンスイッチをオフにする",
            "内蔵キーを取り出す",
            "マイナスドライバーに布を巻く",
            "シフトロック解除穴のカバーを外し、内蔵キーを差し込む",
            "キーを押しながらセレクトレバーのボタンを押して操作する",
        ],
        # シミュレーションユーザー応答制御:
        # ガイド完了後に「動きましたか？」と聞かれた場合、肯定応答で完了に導く
        "user_response_overrides": {
            "動きましたか": "はい、動きました。ありがとうございます",
            "確認してください": "確認しました",
            "動くかどうか": "はい、動くようになりました",
        },
    },
    {
        "id": 20,
        "category": "ブレーキ異音",
        "symptom": "ブレーキを踏むとキーキーと異音がする",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "medium",
        "expected_action": "ask_question",
        "expected_coverage": "partially_covered",  # ブレーキ(P.153)、ABS音(P.154)の関連記載あり
        "max_expected_turns": 3,
        "expected_final_action": "escalate",
        "ground_truth": (
            "マニュアルにブレーキ異音に関する診断手順の記載なし。"
            "P.153「フットブレーキ」には「効きが悪いときはHonda販売店で点検」とあるのみ。"
            "P.154: ABS作動時の振動・作動音は正常との記載あり。"
            "ブレーキ異音のトラブルシューティングはマニュアルに記載がないため、"
            "Honda販売店での点検を案内する。"
        ),
        "manual_steps": [
            "マニュアルにブレーキ異音の診断手順がないことを伝える",
            "Honda販売店での点検を案内する",
        ],
    },
    {
        "id": 21,
        "category": "エンジン始動不良2",
        "symptom": "朝エンジンをかけようとしたが、キュルキュル音はするのにかからない",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "high",
        "expected_action": "ask_question",
        "expected_coverage": "covered",
        "max_expected_turns": 8,
        "expected_final_action": "provide_answer",
        "ground_truth": (
            "マニュアルP.206「エンジンが始動しないとき」: "
            "スターターが回る（キュルキュル音がする）場合は、"
            "エンジンの始動手順（P.141）を再度確認してください。"
            "P.141: パーキングブレーキがかかっていることを確認し、"
            "セレクトレバーがPにあることを確認し、ブレーキペダルを踏みながら"
            "エンジンスイッチを押してください。"
            "イモビライザーシステムの異常で始動できない場合もあります（P.89参照）。"
            "燃料が十分にあるか確認してください（燃料計 P.62）。"
            "ヒューズの点検と交換はP.218を参照。"
        ),
        "manual_steps": [
            "スターターが回っていることを確認する（キュルキュル音=スターター回転）",
            "エンジンの始動手順を再確認する（P.141）",
            "セレクトレバーがPにあることを確認する",
            "ブレーキペダルを踏みながらエンジンスイッチを押す",
            "燃料が十分にあるか確認する（燃料計 P.62参照）",
            "イモビライザーシステムの異常がないか確認する（P.89参照）",
            "ヒューズを点検する（P.218参照）",
            "改善しない場合はHonda販売店に連絡またはロードサービスを手配する",
        ],
        # シミュレーションユーザー応答制御:
        # 「スターターは回りますか？」→ 症状から回っている（キュルキュル音）
        # 「エンジンはかかりますか？」→ かからない（症状そのもの）
        "user_response_overrides": {
            "回りますか": "はい、キュルキュルと音がして回ります",
            "かかりますか": "いいえ、かかりません",
            "始動しますか": "いいえ、始動しません",
        },
    },
    {
        "id": 22,
        "category": "油圧警告灯",
        "symptom": "油圧警告灯が点灯している",
        "vehicle_id": VEHICLE_ID,
        "expected_urgency": "critical",
        "expected_action": "ask_question",
        "expected_coverage": "covered",
        "max_expected_turns": 7,
        "expected_final_action": "provide_answer",
        "ground_truth": (
            "マニュアルP.213「油圧警告灯が点灯したとき」: "
            "エンジン内部を潤滑しているオイルの油圧が低下すると点灯する。"
            "1. ただちに車を安全な場所に停車する。"
            "2. 非常点滅表示灯を点灯させる。"
            "3. エンジンを止めて1分以上待つ。"
            "4. ボンネットを開けてエンジンオイルの量を確認する。"
            "5. オイルが不足している場合は補給する。"
            "6. エンジンをかけて油圧警告灯が10秒以内に消灯するか確認する。"
            "7. 消灯しない場合はエンジンを止めてHonda販売店に連絡する。"
        ),
        "manual_steps": [
            "ただちに安全な場所に停車する",
            "非常点滅表示灯を点灯させる",
            "エンジンを止めて1分以上待つ",
            "ボンネットを開ける",
            "エンジンオイルの量を確認する",
            "オイルが不足している場合は補給する",
            "エンジンをかけて油圧警告灯が10秒以内に消灯するか確認する",
            "消灯しない場合はエンジンを止めてHonda販売店に連絡する",
        ],
        # シミュレーションユーザー応答制御:
        # 「消灯しましたか？」→ 消灯しない（ディーラー連絡が最終手順）
        "user_response_overrides": {
            "消灯しましたか": "いいえ、まだ点灯したままです",
            "消えましたか": "いいえ、消えません",
        },
    },
]
