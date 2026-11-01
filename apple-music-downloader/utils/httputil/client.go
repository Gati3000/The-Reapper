package httputil

import (
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"golang.org/x/net/proxy"
)

// Client is the shared HTTP client used by all Apple API requests.
// It is initialised once via Init() with an optional proxy URL.
var Client = http.DefaultClient

// Init configures the shared Client.
// proxyURL may be empty (no proxy), or any of:
//
//	socks5://user:pass@host:port
//	socks5://host:port
//	http://host:port
//	https://host:port
//
// If the proxyURL is "system" the standard http.DefaultClient is kept as-is
// (honours HTTP_PROXY / HTTPS_PROXY environment variables automatically).
func Init(proxyURL string) error {
	proxyURL = strings.TrimSpace(proxyURL)
	if proxyURL == "" || proxyURL == "system" {
		// keep http.DefaultClient – it already reads HTTP_PROXY env vars
		return nil
	}

	parsed, err := url.Parse(proxyURL)
	if err != nil {
		return fmt.Errorf("invalid proxy URL %q: %w", proxyURL, err)
	}

	var transport *http.Transport

	switch strings.ToLower(parsed.Scheme) {
	case "socks5", "socks5h":
		var auth *proxy.Auth
		if parsed.User != nil {
			pass, _ := parsed.User.Password()
			auth = &proxy.Auth{
				User:     parsed.User.Username(),
				Password: pass,
			}
		}
		dialer, err := proxy.SOCKS5("tcp", parsed.Host, auth, proxy.Direct)
		if err != nil {
			return fmt.Errorf("failed to create SOCKS5 dialer: %w", err)
		}
		transport = &http.Transport{
			Dial:                dialer.Dial,
			TLSHandshakeTimeout: 30 * time.Second,
		}

	case "http", "https":
		transport = &http.Transport{
			Proxy:               http.ProxyURL(parsed),
			TLSHandshakeTimeout: 30 * time.Second,
		}

	default:
		return fmt.Errorf("unsupported proxy scheme %q (supported: socks5, http, https)", parsed.Scheme)
	}

	Client = &http.Client{
		Transport: transport,
		Timeout:   60 * time.Second,
	}
	return nil
}
