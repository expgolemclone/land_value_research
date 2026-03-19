use once_cell::sync::Lazy;
use regex::Regex;

const KANJI_DIGITS: &[(i32, &str)] = &[
    (0, "零"),
    (1, "一"),
    (2, "二"),
    (3, "三"),
    (4, "四"),
    (5, "五"),
    (6, "六"),
    (7, "七"),
    (8, "八"),
    (9, "九"),
    (10, "十"),
];

/// 数値 → 漢数字 (0-99)
pub fn num_to_kanji(n: i32) -> Result<String, String> {
    if !(0..=99).contains(&n) {
        return Err(format!("num_to_kanjiの範囲外です(0-99): {}", n));
    }
    if n <= 10 {
        return Ok(KANJI_DIGITS[n as usize].1.to_string());
    }
    if n < 20 {
        return Ok(format!("十{}", KANJI_DIGITS[(n - 10) as usize].1));
    }
    let tens = n / 10;
    let ones = n % 10;
    if ones == 0 {
        return Ok(format!("{}十", KANJI_DIGITS[tens as usize].1));
    }
    Ok(format!(
        "{}十{}",
        KANJI_DIGITS[tens as usize].1, KANJI_DIGITS[ones as usize].1
    ))
}

/// 漢数字の1文字 → 数値
fn kanji_char_to_int(ch: char) -> Option<i32> {
    match ch {
        '零' | '〇' => Some(0),
        '一' => Some(1),
        '二' => Some(2),
        '三' => Some(3),
        '四' => Some(4),
        '五' => Some(5),
        '六' => Some(6),
        '七' => Some(7),
        '八' => Some(8),
        '九' => Some(9),
        _ => None,
    }
}

/// 漢数字トークン → 数値 (例: "二十三" → 23)
pub fn kanji_to_int(token: &str) -> Option<i32> {
    let token = token.trim();
    if token.is_empty() {
        return None;
    }
    if token == "十" {
        return Some(10);
    }
    // 1文字で十以外
    if token.chars().count() == 1 {
        return kanji_char_to_int(token.chars().next().unwrap());
    }
    // "十" を含む複合表記
    if token.contains('十') {
        let parts: Vec<&str> = token.splitn(2, '十').collect();
        if parts.len() != 2 {
            return None;
        }
        let left = parts[0];
        let right = parts[1];
        let tens = if left.is_empty() {
            1
        } else if left.chars().count() == 1 {
            kanji_char_to_int(left.chars().next().unwrap())?
        } else {
            return None;
        };
        let ones = if right.is_empty() {
            0
        } else if right.chars().count() == 1 {
            kanji_char_to_int(right.chars().next().unwrap())?
        } else {
            return None;
        };
        return Some(tens * 10 + ones);
    }
    None
}

static RE_KANJI_CHOME: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?P<num>[一二三四五六七八九十〇零]+)丁目").unwrap());

static RE_KANJI_BAN: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?P<num>[一二三四五六七八九十〇零]+)(?P<unit>番|号)").unwrap());

/// 漢数字丁目/番/号 → 算用数字に正規化
fn normalize_kanji_number_tokens(addr: &str) -> String {
    let out = RE_KANJI_CHOME
        .replace_all(addr, |caps: &regex::Captures| {
            let num_str = &caps["num"];
            match kanji_to_int(num_str) {
                Some(n) => format!("{}丁目", n),
                None => caps[0].to_string(),
            }
        })
        .to_string();
    RE_KANJI_BAN
        .replace_all(&out, |caps: &regex::Captures| {
            let num_str = &caps["num"];
            let unit = &caps["unit"];
            match kanji_to_int(num_str) {
                Some(n) => format!("{}{}", n, unit),
                None => caps[0].to_string(),
            }
        })
        .to_string()
}

/// 全角数字・ダッシュ等を半角に変換し、郵便番号記号・全角スペースを除去
pub fn normalize_addr(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for ch in s.trim().chars() {
        match ch {
            '０'..='９' => out.push((ch as u32 - '０' as u32 + b'0' as u32) as u8 as char),
            '－' | 'ー' | '―' | '−' => out.push('-'),
            '〒' | '\u{3000}' => {} // 除去
            _ => out.push(ch),
        }
    }
    normalize_kanji_number_tokens(&out)
}

static RE_TOKYO: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^東京都(?P<muni>.+?(?:区|市|町|村))(?P<rest>.*)$").unwrap());

/// 「東京都{区市町村}{rest}」の分割
pub fn split_tokyo_municipality(addr: &str) -> (Option<String>, String) {
    let a = normalize_addr(addr);
    match RE_TOKYO.captures(&a) {
        Some(caps) => (Some(caps["muni"].to_string()), caps["rest"].to_string()),
        None => (None, a),
    }
}

static RE_CHOME: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?P<town>.+?)(?P<chome>\d+)丁目(?P<rest>.*)$").unwrap());

static RE_HYPHEN: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?P<town>.+?)(?P<chome>\d+)-(?P<block>\d+)(?:-(?P<go>\d+))?.*$").unwrap()
});

static RE_BLOCK_NO_CHOME: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?P<town>.+?)(?P<block>\d+)(?:番(?:地)?|号).*$").unwrap());

static RE_FIRST_NUM: Lazy<Regex> = Lazy::new(|| Regex::new(r"(\d{1,4})").unwrap());

static RE_TOWN_ONLY: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^(?:[^\d,，、]+|.+(?:町|丁目))$").unwrap());

/// 町名/丁目/街区の粗い推定
pub fn parse_town_chome_block(addr: &str) -> (Option<String>, Option<i32>, Option<i32>) {
    let a = normalize_addr(addr);
    let (_, rest) = split_tokyo_municipality(&a);
    let rest = rest.trim_start();

    // 1) N丁目パターン
    if let Some(caps) = RE_CHOME.captures(rest) {
        let town = caps["town"].to_string();
        let chome: i32 = caps["chome"].parse().unwrap();
        let after = &caps["rest"];
        let block = RE_FIRST_NUM
            .captures(after)
            .map(|m| m[1].parse::<i32>().unwrap());
        return (Some(town), Some(chome), block);
    }

    // 2) ハイフン形式
    if let Some(caps) = RE_HYPHEN.captures(rest) {
        let town = caps["town"].to_string();
        let chome: i32 = caps["chome"].parse().unwrap();
        let block: i32 = caps["block"].parse().unwrap();
        return (Some(town), Some(chome), Some(block));
    }

    // 3) 丁目なし番地
    if let Some(caps) = RE_BLOCK_NO_CHOME.captures(rest) {
        let town = caps["town"].trim().to_string();
        let block: i32 = caps["block"].parse().unwrap();
        return (Some(town), None, Some(block));
    }

    // 4) 町名のみ
    if !rest.is_empty() && RE_TOWN_ONLY.is_match(rest) {
        return (Some(rest.to_string()), None, None);
    }

    (None, None, None)
}

/// 「{町名}{漢数字}丁目」の構築
pub fn build_oaza_chome_name(town: &str, chome: i32) -> String {
    format!("{}{}丁目", town, num_to_kanji(chome).unwrap())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_num_to_kanji() {
        assert_eq!(num_to_kanji(0).unwrap(), "零");
        assert_eq!(num_to_kanji(1).unwrap(), "一");
        assert_eq!(num_to_kanji(10).unwrap(), "十");
        assert_eq!(num_to_kanji(11).unwrap(), "十一");
        assert_eq!(num_to_kanji(20).unwrap(), "二十");
        assert_eq!(num_to_kanji(35).unwrap(), "三十五");
        assert_eq!(num_to_kanji(99).unwrap(), "九十九");
        assert!(num_to_kanji(100).is_err());
        assert!(num_to_kanji(-1).is_err());
    }

    #[test]
    fn test_kanji_to_int() {
        assert_eq!(kanji_to_int("一"), Some(1));
        assert_eq!(kanji_to_int("十"), Some(10));
        assert_eq!(kanji_to_int("十一"), Some(11));
        assert_eq!(kanji_to_int("二十三"), Some(23));
        assert_eq!(kanji_to_int("九十九"), Some(99));
        assert_eq!(kanji_to_int("三"), Some(3));
        assert_eq!(kanji_to_int(""), None);
    }

    #[test]
    fn test_parse_town_chome_block_chome_with_block() {
        let (t, c, b) = parse_town_chome_block("東京都中央区日本橋1丁目15番3号");
        assert_eq!(t.as_deref(), Some("日本橋"));
        assert_eq!(c, Some(1));
        assert_eq!(b, Some(15));
    }

    #[test]
    fn test_parse_town_chome_block_hyphen() {
        let (t, c, b) = parse_town_chome_block("東京都港区六本木3-4-33");
        assert_eq!(t.as_deref(), Some("六本木"));
        assert_eq!(c, Some(3));
        assert_eq!(b, Some(4));
    }

    #[test]
    fn test_parse_town_chome_block_no_chome() {
        let (t, c, b) = parse_town_chome_block("東京都中央区日本橋兜町11番5号");
        assert_eq!(t.as_deref(), Some("日本橋兜町"));
        assert_eq!(c, None);
        assert_eq!(b, Some(11));
    }

    #[test]
    fn test_parse_town_chome_block_town_only() {
        let (t, c, b) = parse_town_chome_block("東京都中央区日本橋兜町");
        assert_eq!(t.as_deref(), Some("日本橋兜町"));
        assert_eq!(c, None);
        assert_eq!(b, None);
    }

    #[test]
    fn test_normalize_fullwidth() {
        let result = normalize_addr("東京都港区六本木３丁目");
        assert!(result.contains("3丁目"));
    }

    #[test]
    fn test_normalize_kanji_chome() {
        let result = normalize_addr("東京都港区六本木三丁目");
        assert!(result.contains("3丁目"));
    }

    #[test]
    fn test_normalize_strips_postal() {
        let result = normalize_addr("〒100-0005 東京都千代田区");
        assert!(!result.contains('〒'));
    }

    #[test]
    fn test_normalize_fullwidth_dash() {
        let result = normalize_addr("六本木３－４");
        assert!(result.contains("3-4"));
    }

    #[test]
    fn test_split_tokyo_municipality_ku() {
        let (muni, rest) = split_tokyo_municipality("東京都中央区日本橋");
        assert_eq!(muni.as_deref(), Some("中央区"));
        assert_eq!(rest, "日本橋");
    }

    #[test]
    fn test_split_tokyo_municipality_shi() {
        let (muni, rest) = split_tokyo_municipality("東京都八王子市元本郷町");
        assert_eq!(muni.as_deref(), Some("八王子市"));
        assert_eq!(rest, "元本郷町");
    }

    #[test]
    fn test_split_tokyo_municipality_non_tokyo() {
        let (muni, _) = split_tokyo_municipality("大阪府大阪市");
        assert!(muni.is_none());
    }

    #[test]
    fn test_build_oaza_chome_name() {
        assert_eq!(build_oaza_chome_name("六本木", 3), "六本木三丁目");
        assert_eq!(build_oaza_chome_name("日本橋", 1), "日本橋一丁目");
    }
}
