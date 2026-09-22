import { useState, useEffect, useRef, useCallback } from "react";

export type CallStatus = "idle" | "connecting" | "connected" | "disconnected" | "error";
export type AIStatus = "idle" | "transcribing" | "thinking" | "speaking";

interface UseVoiceCallProps {
  backendUrl?: string;
  silenceTimeoutMs?: number; // Time of silence to assume user finished speaking
  silenceThreshold?: number; // RMS volume threshold for VAD (0.01 - 0.05)
  useBrowserSpeech?: boolean; // Toggle to use browser speech recognition & synthesis (default: true)
}

export function useVoiceCall({
  backendUrl,
  silenceTimeoutMs = 1500,
  silenceThreshold = 0.015,
  useBrowserSpeech = true,
}: UseVoiceCallProps = {}) {
  const [callStatus, setCallStatus] = useState<CallStatus>("idle");
  const callStatusRef = useRef<CallStatus>("idle");
  const [aiStatus, setAiStatus] = useState<AIStatus>("idle");
  const [userTranscription, setUserTranscription] = useState("");
  const [aiTranscription, setAiTranscription] = useState("");
  const [isMuted, setIsMuted] = useState(false);
  const isMutedRef = useRef(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const isUsingBrowserSpeechRef = useRef(false);

  const updateCallStatus = useCallback((status: CallStatus) => {
    setCallStatus(status);
    callStatusRef.current = status;
  }, []);

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  
  // Real-time volume measurement (VAD) variables
  const analyserRef = useRef<AnalyserNode | null>(null);
  const isSpeakingRef = useRef(false);
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const speechStartedTimeRef = useRef<number | null>(null);
  
  // Audio playback variables (for AI responses)
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const aiStatusRef = useRef<AIStatus>("idle");

  // Browser speech recognition & synthesis refs
  const recognitionRef = useRef<any>(null);

  // Keep ref to latest states for callbacks
  useEffect(() => {
    aiStatusRef.current = aiStatus;
  }, [aiStatus]);

  useEffect(() => {
    isMutedRef.current = isMuted;
  }, [isMuted]);

  const getWsUrl = useCallback(() => {
    if (backendUrl) {
      let url = backendUrl.replace(/^http/, "ws");
      if (!url.endsWith("/ws/voice-call")) {
        url = url.replace(/\/$/, "") + "/ws/voice-call";
      }
      return url;
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    // Fallback to localhost if host is not set
    const finalHost = host.includes("localhost") || !host ? "localhost:8010" : host;
    return `${protocol}//${finalHost}/ws/voice-call`;
  }, [backendUrl]);

  // Stop current playing audio
  const stopPlayback = useCallback(() => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
  }, []);

  // Send an interrupt signal to the backend and stop playback locally
  const triggerInterruption = useCallback(() => {
    stopPlayback();
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "interrupt" }));
      console.log("Sent interrupt to backend due to user starting to speak");
    }
  }, [stopPlayback]);

  // Play audio response received from backend
  const playAudioResponse = useCallback((audioUrl: string) => {
    stopPlayback();
    
    const audio = new Audio(audioUrl);
    currentAudioRef.current = audio;
    
    audio.onended = () => {
      currentAudioRef.current = null;
      setAiStatus("idle");
    };
    
    audio.onerror = (e) => {
      console.error("Audio playback error:", e);
      currentAudioRef.current = null;
      setAiStatus("idle");
    };

    audio.play().catch((err) => {
      console.warn("Audio autoplay blocked or failed:", err);
      setAiStatus("idle");
    });
  }, [stopPlayback]);

  // Client-side Web Speech Synthesis (TTS) Fallback
  const speakText = useCallback((text: string) => {
    if (!window.speechSynthesis) return;

    // Stop any existing TTS playback
    window.speechSynthesis.cancel();

    // Temporarily pause speech recognition to avoid hearing its own speech
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch (e) {
        // Already stopped
      }
    }

    // Clean up markdown syntax for clean speech
    const cleanText = text
      .replace(/[*_`#\-]/g, "")
      .replace(/\n+/g, " ")
      .trim();

    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.lang = "vi-VN";

    utterance.onstart = () => {
      setAiStatus("speaking");
    };

    utterance.onend = () => {
      setAiStatus("idle");
      // Resume listening
      if (callStatusRef.current === "connected" && !isMutedRef.current && recognitionRef.current) {
        try {
          recognitionRef.current.start();
        } catch (e) {
          console.error(e);
        }
      }
    };

    utterance.onerror = (e) => {
      console.error("SpeechSynthesis error:", e);
      setAiStatus("idle");
      // Resume listening on error
      if (callStatusRef.current === "connected" && !isMutedRef.current && recognitionRef.current) {
        try {
          recognitionRef.current.start();
        } catch (err) {
          console.error(err);
        }
      }
    };

    // Find a Vietnamese voice if available, otherwise browser will use default vi-VN voice
    const voices = window.speechSynthesis.getVoices();
    const viVoice = voices.find(v => v.lang === "vi-VN" || v.lang.startsWith("vi"));
    if (viVoice) {
      utterance.voice = viVoice;
    }

    window.speechSynthesis.speak(utterance);
  }, []);

  // Browser-side Web Speech Recognition (STT) setup
  const initBrowserSpeech = useCallback((ws: WebSocket) => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn("Browser SpeechRecognition is not supported in this browser.");
      setErrorMessage("Trình duyệt không hỗ trợ nhận diện giọng nói.");
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "vi-VN";

    let finalTranscript = "";

    recognition.onstart = () => {
      console.log("Browser speech recognition started");
    };

    recognition.onerror = (event: any) => {
      console.error("Speech recognition error:", event.error);
      if (event.error === "not-allowed") {
        setErrorMessage("Quyền truy cập micro bị từ chối. Vui lòng bật micro trên trình duyệt của bạn.");
        updateCallStatus("error");
      } else if (event.error === "network") {
        setErrorMessage("Lỗi kết nối mạng nhận dạng giọng nói (Google Speech API).");
      } else {
        setErrorMessage(`Lỗi nhận diện giọng nói: ${event.error}`);
      }
    };

    recognition.onend = () => {
      console.log("Browser speech recognition ended");
      // Auto-restart if call is still active, mic is not muted, and AI is not speaking/thinking
      if (
        callStatusRef.current === "connected" &&
        !isMutedRef.current &&
        aiStatusRef.current === "idle"
      ) {
        try {
          recognition.start();
        } catch (e) {
          // Already running or starting
        }
      }
    };

    recognition.onresult = (event: any) => {
      if (isMutedRef.current || aiStatusRef.current !== "idle") {
        return;
      }

      let interimTranscript = "";
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript + " ";
        } else {
          interimTranscript += event.results[i][0].transcript;
        }
      }

      // Update state for UI transcription display
      const currentText = finalTranscript.trim() + " " + interimTranscript.trim();
      if (currentText.trim()) {
        setUserTranscription(currentText.trim());
      }

      // Silence detection timer for sending final transcript to backend
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
      }

      if (finalTranscript.trim()) {
        silenceTimerRef.current = setTimeout(() => {
          if (finalTranscript.trim() && ws.readyState === WebSocket.OPEN) {
            console.log("Sending transcribed speech text to backend:", finalTranscript.trim());
            ws.send(JSON.stringify({ type: "speech_text", text: finalTranscript.trim() }));
            finalTranscript = ""; // Reset after sending
          }
        }, 1500); // 1.5s of silence after final result is safer
      }
    };

    recognitionRef.current = recognition;
    try {
      recognition.start();
    } catch (e) {
      console.error("Failed to start speech recognition:", e);
    }
  }, [updateCallStatus]);

  // Upload an image during the call for VLM analysis
  const uploadImage = useCallback((base64Image: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: "image",
          data: base64Image,
        })
      );
      return true;
    }
    return false;
  }, []);

  const endCall = useCallback(() => {
    console.log("Ending voice call...");
    
    // Clear timers
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    
    // Stop recording (VAD mode)
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      try {
        mediaRecorderRef.current.stop();
      } catch (e) {
        console.error(e);
      }
    }
    
    // Stop tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    
    // Close AudioContext
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(console.error);
      audioContextRef.current = null;
    }
    
    // Stop SpeechSynthesis
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    
    // Stop SpeechRecognition
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch (e) {
        console.error(e);
      }
      recognitionRef.current = null;
    }

    // Close WS connection
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    
    // Stop playback
    stopPlayback();
    
    updateCallStatus("disconnected");
    setAiStatus("idle");
    setUserTranscription("");
    setAiTranscription("");
  }, [stopPlayback, updateCallStatus]);

  const startCall = useCallback(async () => {
    try {
      updateCallStatus("connecting");
      setUserTranscription("");
      setAiTranscription("");
      setErrorMessage(null);

      // Determine if we should and can use browser-side Speech Recognition
      const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      const actualUseBrowserSpeech = useBrowserSpeech && !!SpeechRecognition;
      isUsingBrowserSpeechRef.current = actualUseBrowserSpeech;
      console.log("Voice Call Mode: actualUseBrowserSpeech =", actualUseBrowserSpeech);
      
      // Setup WebSocket Connection
      const wsUrl = getWsUrl();
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      // ── Connection timeout: if not opened within 7s, report error ──
      const connectionTimeoutId = setTimeout(() => {
        if (callStatusRef.current === "connecting") {
          console.error("WebSocket connection timed out after 7 seconds.");
          setErrorMessage("Không thể kết nối tới máy chủ. Kiểm tra lại backend hoặc URL ngrok.");
          updateCallStatus("error");
          ws.close();
        }
      }, 7000);

      ws.onopen = () => {
        clearTimeout(connectionTimeoutId);
        console.log("Voice Call WS Opened");
        updateCallStatus("connected");
        ws.send(JSON.stringify({ type: "start" }));
        
        if (actualUseBrowserSpeech) {
          initBrowserSpeech(ws);
        }
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          
          switch (message.type) {
            case "ai_status":
              setAiStatus(message.status);
              break;
            case "user_transcription":
              setUserTranscription(message.text);
              break;
            case "ai_transcription":
              setAiTranscription(message.text);
              if (isUsingBrowserSpeechRef.current) {
                speakText(message.text);
              }
              break;
            case "audio_response":
              if (isUsingBrowserSpeechRef.current && window.speechSynthesis) {
                window.speechSynthesis.cancel();
              }
              playAudioResponse(message.audio);
              break;
            case "system":
              console.log("System message:", message.message);
              break;
            case "error":
              console.error("Error from backend:", message.message);
              setErrorMessage(message.message || "Lỗi từ máy chủ.");
              updateCallStatus("error");
              break;
          }
        } catch (e) {
          console.error("Failed to parse voice-call message", e);
        }
      };

      ws.onclose = () => {
        console.log("Voice Call WS Closed");
        if (callStatusRef.current === "connected") {
          updateCallStatus("disconnected");
        }
      };

      ws.onerror = (err) => {
        console.error("Voice Call WS Error:", err);
        setErrorMessage("Lỗi kết nối máy chủ cuộc gọi (WebSocket).");
        updateCallStatus("error");
      };

      if (!actualUseBrowserSpeech) {
        console.log("Initializing local MediaRecorder + VAD for server-side STT fallback...");
        // Initialize Microphone Audio Stream for server-side processing
        const stream = await navigator.mediaDevices.getUserMedia({ 
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true
          }
        });
        streamRef.current = stream;
        
        // Connect stream VAD once WS is open
        if (ws.readyState === WebSocket.OPEN) {
          startAudioVAD(stream);
        } else {
          ws.addEventListener("open", () => startAudioVAD(stream), { once: true });
        }
      }

    } catch (err: any) {
      console.error("Microphone access denied or error:", err);
      setErrorMessage("Không thể truy cập Micro. Vui lòng cấp quyền micro cho trang web.");
      updateCallStatus("error");
      endCall();
    }
  }, [getWsUrl, playAudioResponse, endCall, updateCallStatus, useBrowserSpeech, initBrowserSpeech, speakText]);

  // VAD algorithm running locally in browser (only for server-side processing)
  const startAudioVAD = (stream: MediaStream) => {
    const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
    audioContextRef.current = audioContext;

    const source = audioContext.createMediaStreamSource(stream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    analyserRef.current = analyser;

    let options = {};
    if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
      options = { mimeType: "audio/webm;codecs=opus" };
    } else if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) {
      options = { mimeType: "audio/ogg;codecs=opus" };
    }
    
    const mediaRecorder = new MediaRecorder(stream, options);
    mediaRecorderRef.current = mediaRecorder;

    mediaRecorder.ondataavailable = async (e) => {
      if (e.data.size > 0 && wsRef.current && wsRef.current.readyState === WebSocket.OPEN && !isMuted) {
        const reader = new FileReader();
        reader.onloadend = () => {
          const base64data = (reader.result as string).split(",")[1];
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(
              JSON.stringify({
                type: "audio_chunk",
                data: base64data,
              })
            );
          }
        };
        reader.readAsDataURL(e.data);
      }
    };

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Float32Array(bufferLength);

    const checkVolume = () => {
      if (!analyserRef.current || callStatusRef.current === "disconnected") return;
      
      analyserRef.current.getFloatTimeDomainData(dataArray);
      
      let sum = 0;
      for (let i = 0; i < bufferLength; i++) {
        sum += dataArray[i] * dataArray[i];
      }
      const rms = Math.sqrt(sum / bufferLength);

      if (rms > silenceThreshold) {
        if (!isSpeakingRef.current) {
          isSpeakingRef.current = true;
          speechStartedTimeRef.current = Date.now();
          console.log("User speech detected!");
          
          if (aiStatusRef.current === "speaking") {
            triggerInterruption();
          }

          if (mediaRecorderRef.current && mediaRecorderRef.current.state === "inactive") {
            mediaRecorderRef.current.start(100);
          }
        }
        
        if (silenceTimerRef.current) {
          clearTimeout(silenceTimerRef.current);
          silenceTimerRef.current = null;
        }
      } else {
        if (isSpeakingRef.current) {
          if (!silenceTimerRef.current) {
            silenceTimerRef.current = setTimeout(() => {
              console.log("User finished speaking (Silence timeout reached)");
              
              isSpeakingRef.current = false;
              speechStartedTimeRef.current = null;
              
              if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
                mediaRecorderRef.current.stop();
                if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                  wsRef.current.send(JSON.stringify({ type: "speech_done" }));
                }
              }
              silenceTimerRef.current = null;
            }, silenceTimeoutMs);
          }
        }
      }

      requestAnimationFrame(checkVolume);
    };

    requestAnimationFrame(checkVolume);
  };

  const toggleMute = () => {
    setIsMuted((prev) => {
      const next = !prev;
      if (streamRef.current) {
        streamRef.current.getAudioTracks().forEach((track) => {
          track.enabled = !next;
        });
      }
      
      if (isUsingBrowserSpeechRef.current && recognitionRef.current) {
        if (next) {
          try {
            recognitionRef.current.stop();
          } catch (e) {
            console.error(e);
          }
        } else if (aiStatusRef.current === "idle" && callStatusRef.current === "connected") {
          try {
            recognitionRef.current.start();
          } catch (e) {
            console.error(e);
          }
        }
      }
      
      return next;
    });
  };

  return {
    callStatus,
    aiStatus,
    userTranscription,
    aiTranscription,
    isMuted,
    errorMessage,
    startCall,
    endCall,
    toggleMute,
    uploadImage,
  };
}
