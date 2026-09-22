import asyncio
import base64
import httpx
import logging
import subprocess
import tempfile
import os
from typing import Optional, List, Dict, AsyncGenerator
from openai import AsyncOpenAI
from backend.app.core.config import NVIDIA_API_KEY, NVIDIA_SPEECH_API_URL

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

logger = logging.getLogger("nvidia_service")

def convert_to_wav(audio_bytes: bytes) -> bytes:
    """
    Convert WebM/Opus or any audio format to 16kHz mono WAV using ffmpeg.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_in:
        temp_in.write(audio_bytes)
        temp_in_path = temp_in.name
    
    temp_out_path = temp_in_path + ".wav"
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_in_path,
            "-ar", "16000",
            "-ac", "1",
            temp_out_path
        ]
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            
        subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            check=True, 
            startupinfo=startupinfo
        )
        
        with open(temp_out_path, "rb") as f:
            wav_bytes = f.read()
        return wav_bytes
    finally:
        try:
            if os.path.exists(temp_in_path):
                os.remove(temp_in_path)
            if os.path.exists(temp_out_path):
                os.remove(temp_out_path)
        except Exception as e:
            logger.warning(f"Error cleaning up temp audio files: {e}")

class NvidiaNIMService:
    def __init__(self):
        self.api_key = NVIDIA_API_KEY
        self.base_url = NVIDIA_SPEECH_API_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }
        self.openai_client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key if self.api_key else "no-key"
        )
        self._local_whisper = None
        self._local_tts_model = None
        self._local_tts_tokenizer = None

    def get_local_whisper(self) -> Optional[WhisperModel]:
        """Lazily load the local Whisper model."""
        if WhisperModel is None:
            return None
            
        if self._local_whisper is None:
            logger.info("Loading local Whisper model ('base') for STT...")
            try:
                self._local_whisper = WhisperModel("base", device="cpu", compute_type="int8")
                logger.info("Local Whisper 'base' model loaded successfully!")
            except Exception as e:
                logger.warning(f"Failed to load Whisper 'base', trying 'tiny'... Error: {e}")
                try:
                    self._local_whisper = WhisperModel("tiny", device="cpu", compute_type="int8")
                    logger.info("Local Whisper 'tiny' model loaded successfully!")
                except Exception as e2:
                    logger.error(f"Failed to load local Whisper models completely: {e2}")
                    self._local_whisper = None
        return self._local_whisper

    def get_local_tts(self) -> tuple:
        """Lazily load the local Hugging Face TTS model (facebook/mms-tts-vie)."""
        if self._local_tts_model is None:
            logger.info("Loading local Hugging Face TTS model ('facebook/mms-tts-vie')...")
            try:
                from transformers import VitsModel, AutoTokenizer
                model_id = "facebook/mms-tts-vie"
                self._local_tts_model = VitsModel.from_pretrained(model_id)
                self._local_tts_tokenizer = AutoTokenizer.from_pretrained(model_id)
                logger.info("Local Hugging Face TTS model loaded successfully!")
            except Exception as e:
                logger.error(f"Failed to load local Hugging Face TTS model: {e}")
                self._local_tts_model = None
                self._local_tts_tokenizer = None
        return self._local_tts_model, self._local_tts_tokenizer

    async def speech_to_text(self, audio_bytes: bytes, filename: str = "audio.wav") -> str:
        """Transcribe Vietnamese audio using local WhisperModel or fallback APIs."""
        # 1. Convert input audio bytes to standard WAV first
        try:
            wav_bytes = convert_to_wav(audio_bytes)
            if not wav_bytes:
                logger.error("Audio conversion returned empty bytes.")
                wav_bytes = audio_bytes
        except Exception as conv_err:
            logger.error(f"Failed to convert audio to WAV: {conv_err}")
            wav_bytes = audio_bytes

        # 2. Try Local Whisper Model (Hugging Face)
        try:
            model = self.get_local_whisper()
            if model is not None:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_wav:
                    temp_wav.write(wav_bytes)
                    temp_wav_path = temp_wav.name
                
                try:
                    segments, info = model.transcribe(temp_wav_path, beam_size=5, language="vi")
                    text = "".join([seg.text for seg in segments]).strip()
                    if text:
                        logger.info(f"Local Whisper STT success: '{text}' (Language: {info.language})")
                        return text
                finally:
                    try:
                        os.remove(temp_wav_path)
                    except:
                        pass
                logger.warning("Local Whisper STT returned empty result. Trying Google STT Fallback...")
        except Exception as whisper_err:
            logger.warning(f"Error running local Whisper model: {whisper_err}. Trying Google STT Fallback...")

        # 3. Fallback to local SpeechRecognition + Google Web Speech API
        try:
            import speech_recognition as sr
            import io
            
            recognizer = sr.Recognizer()
            with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                audio_data = recognizer.record(source)
            
            text = recognizer.recognize_google(audio_data, language="vi-VN")
            logger.info(f"Google STT Fallback success: '{text}'")
            return text
        except Exception as fallback_err:
            logger.warning(f"Google STT Fallback also failed: {fallback_err}. Trying Nvidia NIM ASR Fallback...")
        
        # 4. Fallback to Nvidia NIM ASR API
        url = f"{self.base_url}/audio/transcriptions"
        files = {
            "file": (filename, wav_bytes, "audio/wav"),
            "model": (None, "nvidia/parakeet-ctc-0.6b-vi")
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=self.headers, files=files, timeout=30.0)
                if response.status_code == 200:
                    text = response.json().get("text", "")
                    if text.strip():
                        return text
                logger.error(f"Nvidia STT fallback failed (Status {response.status_code}): {response.text}")
            except Exception as e:
                logger.error(f"Error calling Nvidia STT fallback: {e}")
        
        return ""

    async def text_to_speech(self, text: str) -> bytes:
        """Synthesize Vietnamese speech using local Hugging Face VITS model."""
        import wave
        import struct
        import io

        try:
            model, tokenizer = self.get_local_tts()
            if model is None or tokenizer is None:
                logger.error("Hugging Face TTS model could not be loaded. Returning empty audio.")
                return b""

            logger.info("Synthesizing speech locally using Hugging Face (facebook/mms-tts-vie)...")

            def run_vits_inference():
                import torch
                inputs = tokenizer(text, return_tensors="pt")
                with torch.no_grad():
                    output = model(**inputs).waveform
                return output[0].numpy(), model.config.sampling_rate

            waveform_data, sampling_rate = await asyncio.to_thread(run_vits_inference)

            wav_io = io.BytesIO()
            with wave.open(wav_io, 'wb') as wav_file:
                wav_file.setnchannels(1)   # mono
                wav_file.setsampwidth(2)   # 16-bit
                wav_file.setframerate(sampling_rate)

                for sample in waveform_data:
                    sample = max(-1.0, min(1.0, float(sample)))
                    val = int(sample * 32767)
                    wav_file.writeframes(struct.pack('<h', val))

            wav_bytes = wav_io.getvalue()
            logger.info(f"Hugging Face TTS successful: {len(wav_bytes)} bytes WAV")
            return wav_bytes

        except Exception as e:
            logger.error(f"Hugging Face TTS failed: {e}")
            return b""

    async def chat_completion(
        self, 
        message: str, 
        history: Optional[List[Dict[str, str]]] = None,
        image_bytes: Optional[bytes] = None
    ) -> str:
        """Send message to Llama 3.2 Vision with optional history and image."""
        url = f"{self.base_url}/chat/completions"
        messages = []
        
        system_prompt = (
            "Bạn là một Bác sĩ Chuyên khoa Da liễu và Sức khỏe sinh sản đang tư vấn trực tiếp qua cuộc gọi điện thoại 1-1.\n"
            "Nhiệm vụ của bạn là lắng nghe câu hỏi và quan sát kỹ hình ảnh tổn thương sinh dục được cung cấp (nếu có) để đưa ra lời khuyên nhanh chóng.\n"
            "Hãy trả lời ngắn gọn (khoảng 3-4 câu), thấu cảm, dễ hiểu như đang trò chuyện trực tiếp. "
            "TUYỆT ĐỐI không sử dụng các ký hiệu markdown (như **, #, *), không dùng danh sách gạch đầu dòng hay danh sách số vì câu trả lời sẽ được chuyển thành giọng nói (TTS) để đọc trực tiếp cho bệnh nhân nghe."
        )
        messages.append({"role": "system", "content": system_prompt})

        if history:
            for item in history:
                messages.append({"role": item["role"], "content": item["content"]})
                
        content = []
        if image_bytes:
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
            })
        
        content.append({"type": "text", "text": message})
        messages.append({"role": "user", "content": content})
        
        payload = {
            "model": "meta/llama-3.2-11b-vision-instruct",
            "messages": messages,
            "max_tokens": 512,
            "temperature": 0.5
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=self.headers, json=payload, timeout=30.0)
                if response.status_code != 200:
                    logger.warning("Vision model failed, trying Llama 3.1 8B Instruct")
                    payload["model"] = "meta/llama-3.1-8b-instruct"
                    response = await client.post(url, headers=self.headers, json=payload, timeout=30.0)
                    
                if response.status_code != 200:
                    logger.error(f"Nvidia LLM failed: {response.status_code} - {response.text}")
                    return "Xin lỗi, hiện tại tôi gặp sự cố kết nối dịch vụ y khoa."
                    
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                logger.error(f"Error calling Nvidia LLM: {e}")
                return "Xin lỗi, kết nối y khoa đang bị gián đoạn."

    async def chat_completion_stream(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        image_bytes: Optional[bytes] = None
    ) -> AsyncGenerator[str, None]:
        """Send message to Llama 3.2 Vision and stream the response."""
        messages = []
        system_prompt = (
            "Bạn là một Bác sĩ Chuyên khoa Da liễu và Sức khỏe sinh sản cao cấp. Bạn được cung cấp hình ảnh lâm sàng chụp cận cảnh tổn thương cơ quan sinh dục hoặc vùng da nhạy cảm.\n"
            "Nhiệm vụ của bạn là xem xét kỹ hình ảnh và đọc kỹ câu hỏi của người dùng để trả lời phù hợp:\n\n"
            "THƯỜNG HỢP 1: Nếu người dùng hỏi để chẩn đoán, phân tích hình ảnh, hỏi bệnh gì (ví dụ: 'đây là bị gì?', 'chẩn đoán giúp tôi', 'phân tích ảnh này', 'bị sao thế này'...), bạn PHẢI trình bày câu trả lời của bạn theo đúng cấu trúc báo cáo chi tiết sau:\n\n"
            "🏥 **BÁO CÁO PHÂN TÍCH LÂM SÀNG SƠ BỘ**\n\n"
            "*   **Bệnh lý nghi ngờ (Suspected Condition):** [Nêu rõ tên bệnh bằng tiếng Việt và thuật ngữ y khoa Latinh/Anh, ví dụ: Sùi mào gà - Condyloma acuminatum]\n"
            "*   **Vùng da/Niêm mạc bị ảnh hưởng:** [Vị trí giải phẫu quan sát được trên ảnh]\n"
            "*   **Hình thái tổn thương:** [Mô tả chi tiết đặc điểm hình dạng, màu sắc, mật độ tụ, ví dụ: nốt sùi sần sùi dạng hoa súp lơ, mụn nước xếp thành chùm, vết loét trợt nông...]\n"
            "*   **Kích thước & Sự phân bố:** [Mô tả kích thước ước lượng, phân bố rời rạc hay tập trung thành đám...]\n"
            "*   **Cơ chế bệnh sinh & Tác nhân:** [Giải thích nguyên nhân gây bệnh, ví dụ: virus HPV type 6, 11 hoặc virus HSV...]\n"
            "*   **Khuyến nghị y tế:** \n"
            "    1.  *Chuyên khoa khuyên khám:* [Ví dụ: Da liễu, Phụ sản, Nam khoa...]\n"
            "    2.  *Xét nghiệm cần thiết:* [Ví dụ: Xét nghiệm PCR HPV, xét nghiệm huyết thanh giang mai...]\n"
            "    3.  *Lưu ý an toàn:* [Tuyệt đối không tự ý đốt, nặn, sử dụng thuốc bôi dân gian không rõ nguồn gốc; kiêng quan hệ tình dục để tránh lây nhiễm...]\n\n"
            "TRƯỜNG HỢP 2: Nếu người dùng chỉ trò chuyện, hỏi han chung, tư vấn tâm lý, hỏi về độ nguy hiểm hay lo lắng (ví dụ: 'có nguy hiểm không bác sĩ?', 'tôi lo lắng quá', 'có cần đi viện gấp không'...) mà không hỏi trực tiếp chẩn đoán bệnh gì:\n"
            "Hãy trả lời một cách tự nhiên, thấu cảm, trò chuyện trực tiếp và khoa học như một bác sĩ thân thiện, giải đáp đúng thắc mắc của họ, đồng thời lồng ghép thông tin quan sát được từ ảnh một cách tự nhiên mà KHÔNG dùng cấu trúc báo cáo cứng nhắc ở trên.\n\n"
            "Hãy luôn trả lời bằng tiếng Việt tự nhiên, thấu cảm, khoa học và cực kỳ chuyên nghiệp."
        )
        messages.append({"role": "system", "content": system_prompt})

        if history:
            for item in history:
                messages.append({"role": item["role"], "content": item["content"]})

        content = []
        if image_bytes:
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
            })
        
        content.append({"type": "text", "text": message})
        messages.append({"role": "user", "content": content})

        model = "meta/llama-3.2-11b-vision-instruct"
        try:
            response = await self.openai_client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=1024,
                temperature=0.5,
                stream=True
            )
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.warning(f"Vision stream failed, trying 8B fallback: {e}")
            try:
                response = await self.openai_client.chat.completions.create(
                    model="meta/llama-3.1-8b-instruct",
                    messages=messages,
                    max_tokens=1024,
                    temperature=0.5,
                    stream=True
                )
                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            except Exception as e2:
                logger.error(f"Fallback stream failed: {e2}")
                yield "Xin lỗi, kết nối phân tích ảnh đang bị gián đoạn."
