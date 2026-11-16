package nonecap

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// SolveResult يمثل نتيجة حل الكبتشا من السيرفر
type SolveResult struct {
	Success          bool                    `json:"success"`
	CaptchaType      string                  `json:"captcha_type"`
	Text             string                  `json:"text,omitempty"`
	Token            string                  `json:"token,omitempty"`
	Confidence       float64                 `json:"confidence"`
	ResponseTimeMs   int                     `json:"response_time_ms"`
	Error            string                  `json:"error,omitempty"`
	Metadata         map[string]interface{}  `json:"metadata,omitempty"`
	Analysis         map[string]interface{}  `json:"analysis,omitempty"`
	Alerts           []map[string]interface{} `json:"alerts,omitempty"`
	StrategyUsed     string                  `json:"strategy_used,omitempty"`
}

// AutoResult يمثل نتيجة الحل الذاتي الكامل
type AutoResult struct {
	Result              SolveResult             `json:"result"`
	DetectedType        string                  `json:"detected_type"`
	DetectionConfidence float64                 `json:"detection_confidence"`
	StrategyUsed        string                  `json:"strategy_used"`
	ParamsUsed          map[string]interface{}  `json:"params_used"`
	Escalations         int                     `json:"escalations"`
	Trace               []string                `json:"trace"`
	Alerts              []map[string]interface{} `json:"alerts"`
	TotalTimeMs         int                     `json:"total_time_ms"`
	Experience          map[string]interface{}  `json:"experience,omitempty"`
}

// BaseSolveOptions represents common options for solving
type BaseSolveOptions struct {
	Sitekey     string `json:"sitekey,omitempty"`
	URL         string `json:"url,omitempty"`
	Action      string `json:"action,omitempty"`
	Cdata       string `json:"cdata,omitempty"`
	TargetColor string `json:"target_color,omitempty"`
	MinArea     int    `json:"min_area,omitempty"`
	PSM         int    `json:"psm,omitempty"`
	OEM         int    `json:"oem,omitempty"`
	Preprocess  bool   `json:"preprocess,omitempty"`
	Threshold   string `json:"threshold,omitempty"`
	HumanLike   bool   `json:"human_like,omitempty"`
}

// NoneCap هو العميل الرئيسي لسيرفر NoneCap Clone
type NoneCap struct {
	baseURL  string
	apiKey   string
	http     *http.Client
	timeout  time.Duration
}

// NewNoneCap ينشئ عميلاً جديداً لسيرفر NoneCap Clone
func NewNoneCap(options ...Option) *NoneCap {
	c := &NoneCap{
		baseURL: "http://localhost:8000",
		http:    &http.Client{Timeout: 60 * time.Second},
		timeout: 60 * time.Second,
	}
	for _, opt := range options {
		opt(c)
	}
	return c
}

// Option هو دالة configurational للعميل
type Option func(*NoneCap)

// WithBaseURL يحدد عنوان السيرفر الأساسي
func WithBaseURL(url string) Option {
	return func(c *NoneCap) {
		c.baseURL = strings.TrimRight(url, "/")
	}
}

// WithAPIKey يحدد مفتاح API للمصادقة
func WithAPIKey(key string) Option {
	return func(c *NoneCap) {
		c.apiKey = key
	}
}

// WithTimeout يحدد مهلة الطلب
func WithTimeout(d time.Duration) Option {
	return func(c *NoneCap) {
		c.timeout = d
		c.http.Timeout = d
	}
}

// headers يعيد العناوين الأساسية للطلب
func (c *NoneCap) headers() map[string]string {
	h := make(map[string]string)
	h["Accept"] = "application/json"
	if c.apiKey != "" {
		h["Authorization"] = "Bearer " + c.apiKey
	}
	return h
}

// do ينفذ طلب HTTP ويحلل الاستجابة_JSON
func (c *NoneCap) do(method, path string, body interface{}, result interface{}) error {
	reqURL := c.baseURL + path

	var bodyReader io.Reader
	var contentType string

	if body != nil {
		switch v := body.(type) {
		case string:
			bodyReader = strings.NewReader(v)
			contentType = "application/json"
		case []byte:
			bodyReader = bytes.NewReader(v)
			contentType = "application/json"
		default:
			jsonBytes, err := json.Marshal(v)
			if err != nil {
				return fmt.Errorf("فشل تشفير الطلب: %w", err)
			}
			bodyReader = bytes.NewReader(jsonBytes)
			contentType = "application/json"
		}
	}

	req, err := http.NewRequest(method, reqURL, bodyReader)
	if err != nil {
		return fmt.Errorf("فشل إنشاء الطلب: %w", err)
	}

	for k, v := range c.headers() {
		req.Header.Set(k, v)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("فشل الطلب: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("خطأ في السيرفر %d: %s", resp.StatusCode, string(bodyBytes))
	}

	if result != nil {
		respBytes, err := io.ReadAll(resp.Body)
		if err != nil {
			return fmt.Errorf("فشل قراءة الاستجابة: %w", err)
		}
		if err := json.Unmarshal(respBytes, result); err != nil {
			return fmt.Errorf("فشل تحليل الاستجابة: %w", err)
		}
	}

	return nil
}

// Health يفحص حالة السيرفر
func (c *NoneCap) Health() (map[string]interface{}, error) {
	var result map[string]interface{}
	if err := c.do("GET", "/health", nil, &result); err != nil {
		return nil, err
	}
	return result, nil
}

// Stats يعيد إحصائيات السيرفر
func (c *NoneCap) Stats() (map[string]interface{}, error) {
	var result map[string]interface{}
	if err := c.do("GET", "/stats", nil, &result); err != nil {
		return nil, err
	}
	return result, nil
}

// Auto يعالج كبتشا تلقائياً مع كشف النوع
func (c *NoneCap) Auto(captchaType string, imagePath string, options ...BaseSolveOptions) (*AutoResult, error) {
	// إعداد النموذج المتعدد الأجزاء
	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)

	if imagePath != "" {
		f, err := os.Open(imagePath)
		if err != nil {
			return nil, fmt.Errorf("فشل فتح الصورة: %w", err)
		}
		defer f.Close()

		part, err := writer.CreateFormFile("file", imagePath)
		if err != nil {
			return nil, fmt.Errorf("فشل إنشاء نموذج الملف: %w", err)
		}
		if _, err := io.Copy(part, f); err != nil {
			return nil, fmt.Errorf("فشل قراءة الملف: %w", err)
		}
	}

	if captchaType != "" {
		writer.WriteField("captcha_type", captchaType)
	}
	writer.WriteField("human_like", "false")
	writer.WriteField("max_escalations", "2")

	if len(options) > 0 {
		opt := options[0]
		if opt.URL != "" {
			writer.WriteField("url", opt.URL)
		}
		if opt.Sitekey != "" {
			writer.WriteField("sitekey", opt.Sitekey)
		}
		if opt.HumanLike {
			writer.WriteField("human_like", "true")
		}
		if opt.MaxEscalations > 0 {
			writer.WriteField("max_escalations", fmt.Sprintf("%d", opt.MaxEscalations))
		}
	}

	writer.Close()

	req, err := http.NewRequest("POST", c.baseURL+"/auto", &buf)
	if err != nil {
		return nil, fmt.Errorf("فشل إنشاء الطلب: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	for k, v := range c.headers() {
		req.Header.Set(k, v)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("فشل الطلب: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("خطأ في السيرفر %d: %s", resp.StatusCode, string(bodyBytes))
	}

	var result AutoResult
	respBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("فشل قراءة الاستجابة: %w", err)
	}
	if err := json.Unmarshal(respBytes, &result); err != nil {
		return nil, fmt.Errorf("فشل تحليل الاستجابة: %w", err)
	}
	return &result, nil
}

// SolveImage يحل صورة كبتشا محلياً
func (c *NoneCap) SolveImage(imagePath string, options ...BaseSolveOptions) (*SolveResult, error) {
	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)

	f, err := os.Open(imagePath)
	if err != nil {
		return nil, fmt.Errorf("فشل فتح الصورة: %w", err)
	}
	defer f.Close()

	part, err := writer.CreateFormFile("file", imagePath)
	if err != nil {
		return nil, fmt.Errorf("فشل إنشاء نموذج الملف: %w", err)
	}
	if _, err := io.Copy(part, f); err != nil {
		return nil, fmt.Errorf("فشل قراءة الملف: %w", err)
	}

	writer.WriteField("captcha_type", "image")
	if len(options) > 0 {
		opt := options[0]
		if opt.PSM > 0 {
			writer.WriteField("psm", fmt.Sprintf("%d", opt.PSM))
		}
		if opt.Threshold != "" {
			writer.WriteField("threshold", opt.Threshold)
		}
		if opt.Preprocess {
			writer.WriteField("preprocess", "true")
		}
		if opt.MinArea > 0 {
			writer.WriteField("min_area", fmt.Sprintf("%d", opt.MinArea))
		}
	}

	writer.Close()

	req, err := http.NewRequest("POST", c.baseURL+"/solve/image", &buf)
	if err != nil {
		return nil, fmt.Errorf("فشل إنشاء الطلب: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	for k, v := range c.headers() {
		req.Header.Set(k, v)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("فشل الطلب: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("خطأ في السيرفر %d: %s", resp.StatusCode, string(bodyBytes))
	}

	var body map[string]interface{}
	respBytes, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(respBytes, &body); err != nil {
		return nil, fmt.Errorf("فشل تحليل الاستجابة: %w", err)
	}

	resultData, _ := body["result"].(map[string]interface{})
	result := SolveResult{
		Success:        boolVal(resultData["success"]),
		CaptchaType:    strVal(resultData["captcha_type"]),
		Text:           strVal(resultData["text"]),
		Token:          strVal(resultData["token"]),
		Confidence:     floatVal(resultData["confidence"]),
		ResponseTimeMs: intVal(resultData["response_time_ms"]),
		Error:          strVal(resultData["error"]),
	}
	return &result, nil
}

// SolveURL يحمّل صورة من رابط URL ويحلها تلقائياً
func (c *NoneCap) SolveURL(imageURL string, captchaType string, options ...BaseSolveOptions) (map[string]interface{}, error) {
	payload := map[string]interface{}{
		"url":           imageURL,
		"captcha_type":  captchaType,
		"human_like":    false,
		"max_escalations": 2,
	}
	if len(options) > 0 {
		opt := options[0]
		if opt.Sitekey != "" {
			payload["sitekey"] = opt.Sitekey
		}
		if opt.HumanLike {
			payload["human_like"] = true
		}
	}

	jsonBytes, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("فشل تشفير الطلب: %w", err)
	}

	var result map[string]interface{}
	if err := c.do("POST", "/solve/url", bytes.NewReader(jsonBytes), &result); err != nil {
		return nil, err
	}
	return result, nil
}

// CreateAPIKey ينشئ مفتاح API جديد
func (c *NoneCap) CreateAPIKey(name string) (map[string]interface{}, error) {
	payload := map[string]interface{}{}
	if name != "" {
		payload["name"] = name
	}
	jsonBytes, _ := json.Marshal(payload)

	var result map[string]interface{}
	if err := c.do("POST", "/api/keys", bytes.NewReader(jsonBytes), &result); err != nil {
		return nil, err
	}
	return result, nil
}

// ListAPIKeys يعيد قائمة مفاتيح API
func (c *NoneCap) ListAPIKeys() ([]map[string]interface{}, error) {
	var result []map[string]interface{}
	if err := c.do("GET", "/api/keys", nil, &result); err != nil {
		return nil, err
	}
	return result, nil
}

// DeleteAPIKey يلغي مفتاح API
func (c *NoneCap) DeleteAPIKey(keyID string) (map[string]interface{}, error) {
	var result map[string]interface{}
	if err := c.do("DELETE", "/api/keys/"+url.PathEscape(keyID), nil, &result); err != nil {
		return nil, err
	}
	return result, nil
}

// BulkAuto يرسل دفعة من الكبتشا للحل التلقائي
func (c *NoneCap) BulkAuto(items []map[string]interface{}) (map[string]interface{}, error) {
	payload := map[string]interface{}{
		"items": items,
	}
	jsonBytes, _ := json.Marshal(payload)

	var result map[string]interface{}
	if err := c.do("POST", "/bulk/auto", bytes.NewReader(jsonBytes), &result); err != nil {
		return nil, err
	}
	return result, nil
}

// BulkStatus يعيد حالة مهمة حل جماعية
func (c *NoneCap) BulkStatus(bulkID string) (map[string]interface{}, error) {
	var result map[string]interface{}
	if err := c.do("GET", "/bulk/"+url.PathEscape(bulkID), nil, &result); err != nil {
		return nil, err
	}
	return result, nil
}

// SelfImproveStats يعيد إحصائيات التعلم الذاتي
func (c *NoneCap) SelfImproveStats() (map[string]interface{}, error) {
	var result map[string]interface{}
	if err := c.do("GET", "/self-improve/stats", nil, &result); err != nil {
		return nil, err
	}
	return result, nil
}

// SelfImproveRetrain يعيد تدريب النموذج الذاتي
func (c *NoneCap) SelfImproveRetrain() (map[string]interface{}, error) {
	var result map[string]interface{}
	if err := c.do("POST", "/self-improve/retrain", nil, &result); err != nil {
		return nil, err
	}
	return result, nil
}

// ExperienceStats يعيد إحصائيات خبرة النظام
func (c *NoneCap) ExperienceStats() (map[string]interface{}, error) {
	var result map[string]interface{}
	if err := c.do("GET", "/experience/stats", nil, &result); err != nil {
		return nil, err
	}
	return result, nil
}

// ExperienceKnowledge يعيد إحصائيات قاعدة المعرفة
func (c *NoneCap) ExperienceKnowledge() (map[string]interface{}, error) {
	var result map[string]interface{}
	if err := c.do("GET", "/experience/knowledge", nil, &result); err != nil {
		return nil, err
	}
	return result, nil
}

// ExperienceFind يبحث عن حل معروف لنمط مشابه
func (c *NoneCap) ExperienceFind(captchaType string, features map[string]interface{}) (map[string]interface{}, error) {
	payload := map[string]interface{}{
		"captcha_type": captchaType,
		"features":     features,
	}
	jsonBytes, _ := json.Marshal(payload)

	var result map[string]interface{}
	if err := c.do("POST", "/experience/find", bytes.NewReader(jsonBytes), &result); err != nil {
		return nil, err
	}
	return result, nil
}

// دوال مساعدة

func strVal(v interface{}) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func boolVal(v interface{}) bool {
	if b, ok := v.(bool); ok {
		return b
	}
	return false
}

func floatVal(v interface{}) float64 {
	switch val := v.(type) {
	case float64:
		return val
	case int:
		return float64(val)
	}
	return 0
}

func intVal(v interface{}) int {
	switch val := v.(type) {
	case float64:
		return int(val)
	case int:
		return val
	}
	return 0
}

var _ = io.Reader(nil) // استيراد غير مستخدم للاستخدام المستقبلي
