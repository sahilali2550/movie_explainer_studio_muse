import re
from typing import Dict, Any, List

class MetadataEngine:
    """
    YouTube, TikTok & Reels Universal Viral Social Metadata Suite.
    Generates high-CTR titles, genre-tailored descriptions, ranked SEO tags,
    and engagement pinned comments across 6+ storytelling genres.
    """

    @staticmethod
    def clean_movie_title(raw_title: str) -> str:
        """
        Strips pipes, release years, and spam tags (Full Movie, Blockbuster, Hollywood Film, HD, etc.)
        to extract the clean, pure title (e.g. 'Sera The Untold | Hollywood Blockbuster Full Movie HD' -> 'Sera The Untold').
        """
        if not raw_title:
            return "This Viral Story"

        # Split by common title separators: |, •, /, –, —
        # Typically the actual movie name is in the first segment
        segments = re.split(r'[\s]*[|•\/\–\—][\s]*', raw_title)
        title = segments[0].strip() if segments else raw_title.strip()

        # Remove trailing/leading parentheses or brackets like (2024), [HD], (Full Movie)
        title = re.sub(r'[\(\[\{][^\)\]\}]*[\)\]\}]', ' ', title)

        # Remove noise words and spam patterns
        noise_patterns = [
            r'\b(?:full\s*movie|blockbuster|hollywood|bollywood|tollywood|film|hindi\s*dubbed|urdu\s*dubbed|english\s*subtitles|subtitles|trailer|teaser|recap|ending\s*explained|explained|action\s*movie|hd|4k|1080p|720p|bluray|official)\b',
            r'\b(?:19\d\d|20\d\d)\b',  # Years like 1999, 2023, 2024
        ]
        for pat in noise_patterns:
            title = re.sub(pat, ' ', title, flags=re.IGNORECASE)

        # Clean underscores, dashes, multiple spaces
        title = title.replace('_', ' ').replace('-', ' ').strip()
        title = re.sub(r'\s+', ' ', title).strip()

        if not title or len(title) < 2 or title.lower() in ["movie", "story", "video"]:
            fallback = segments[0].strip() if segments else raw_title.strip()
            fallback = re.sub(r'[|_]', ' ', fallback).strip()
            return fallback or "This Viral Story"

        return title

    @staticmethod
    def generate_viral_metadata(
        movie_title: str,
        script_snippet: str,
        lang: str = "en",
        genre: str = "movie_recap"
    ) -> Dict[str, Any]:
        """
        Generates click-to-copy metadata package tailored to the video's language and genre.
        Supports: movie_recap, biography, documentary, true_crime, tech_science, video_essay.
        """
        clean_title = MetadataEngine.clean_movie_title(movie_title)
        if not clean_title or clean_title == "Movie Story Explanation":
            clean_title = "This Viral Story"

        clean_tag_title = re.sub(r'[^\w\u0600-\u06FF\u0900-\u097F]', '', clean_title.replace(' ', ''))
        if not clean_tag_title:
            clean_tag_title = "ViralStory"

        # Genre-specific hooks and descriptions
        if genre == "biography":
            if lang in ["ur", "hi"]:
                titles = [
                    f"👑 {clean_title} کی حقیقی داستان جو تاریخ نے چھپا دی! (True Life Story)",
                    f"🔥 غربت سے ارب پتی بننے تک! {clean_title} کی مکمل بایوگرافی",
                    f"⚠️ وہ راز جس نے دنیا ہلا دی! {clean_title} Documentary & Life Lessons"
                ]
                desc_hook = f"آج کی اس ویڈیو میں ہم آپ کے سامنے پیش کر رہے ہیں {clean_title} کی سچی، پراسرار اور ولولہ انگیز داستان حیات۔ جانیں اس عظیم شخصیت کے عروج و زوال کا اصل سچ!"
                pinned = "💬 اس عظیم شخصیت کی زندگی کا سب سے متاثر کن پہلو آپ کو کون سا لگا؟ کمنٹ میں ضرور بتائیں! 👇"
                tags = [f"{clean_title} biography", f"{clean_title} true story", "success story", "history documentary", "life lessons"]
                hashtags = [f"#{clean_tag_title}", "#Biography", "#SuccessStory", "#TrueStory", "#Inspiration"]
            else:
                titles = [
                    f"👑 The Untold True Story of {clean_title} That Changed History!",
                    f"🔥 From Nothing to Everything: The Real Story of {clean_title}",
                    f"⚠️ The Secret Life of {clean_title} Exposed! (Biography Documentary)"
                ]
                desc_hook = f"In this deep dive, we uncover the astonishing true life story and legacy of {clean_title}. From humble beginnings to global impact, discover the truth."
                pinned = "💬 What do you think was their defining moment of greatness? Drop your thoughts below! 👇"
                tags = [f"{clean_title} biography", f"{clean_title} real story", "biographical documentary", "success story", "historical icons"]
                hashtags = [f"#{clean_tag_title}", "#Biography", "#TrueStory", "#HistoryDocumentary", "#Inspiration"]

        elif genre in ["documentary", "true_crime"]:
            if lang in ["ur", "hi"]:
                titles = [
                    f"🔍 {clean_title} کا وہ خوفناک سچ جو پولیس بھی نہ سلجھا سکی! (Forensic Investigation)",
                    f"⚠️ سب سے بڑی سازش کا پردہ فاش! {clean_title} Crime Documentary",
                    f"😱 آخری کال کے بعد کیا ہوا؟ {clean_title} کی دل دہلا دینے والی حقیقت"
                ]
                desc_hook = f"ایک لرزہ خیز اور پراسرار کیس کی مکمل فارنزک اور تفتیشی دستاویز: {clean_title}۔ ہر پہلو کو ثبوت کے ساتھ دیکھیں۔"
                pinned = "💬 آپ کے خیال میں اصل مجرم کون ہے؟ کمنٹس میں اپنی تفتیشی تھیوری شیئر کریں! 👇"
                tags = [f"{clean_title} crime case", f"{clean_title} documentary", "true crime urdu", "unsolved mystery", "forensic files"]
                hashtags = [f"#{clean_tag_title}", "#TrueCrime", "#MysteryCase", "#Investigation", "#CrimeDocumentary"]
            else:
                titles = [
                    f"🔍 The Chilling Truth Behind {clean_title} (Forensic Crime Documentary)",
                    f"⚠️ The Crime That Stunned Everyone: What Really Happened to {clean_title}?",
                    f"😱 The Unsolved Case of {clean_title} Finally Explained!"
                ]
                desc_hook = f"A forensic investigation breaking down the chilling mystery of {clean_title}. We examine the evidence, suspects, and hidden truths."
                pinned = "💬 What is your theory on what really happened here? Let us know in the comments below! 👇"
                tags = [f"{clean_title} investigation", f"{clean_title} true crime", "crime documentary", "cold case", "forensic investigation"]
                hashtags = [f"#{clean_tag_title}", "#TrueCrime", "#Investigation", "#ColdCase", "#Documentary"]

        elif genre == "tech_science":
            if lang in ["ur", "hi"]:
                titles = [
                    f"🚀 {clean_title} نے دنیا کا نقشہ کیسے بدلا؟ (Tech Revolution)",
                    f"💡 اربوں ڈالر کی ایجاد! {clean_title} Case Study & Future Impact",
                    f"⚠️ وہ ٹیکنالوجی جس سے دنیا ڈرتی ہے! {clean_title} Science Breakdown"
                ]
                desc_hook = f"ٹیکنالوجی اور سائنس کی دنیا کا سب سے بڑا انقلابی بریک تھرو: {clean_title}۔ جانیں یہ ایجاد مستقبل کو کیسے بدلنے جا رہی ہے۔"
                pinned = "💬 کیا آپ کو لگتا ہے کہ یہ ٹیکنالوجی انسانیت کے لیے فائدہ مند ہے یا خطرناک؟ اپنی رائے دیں! 👇"
                tags = [f"{clean_title} case study", f"{clean_title} tech breakdown", "future science", "silicon valley", "innovation"]
                hashtags = [f"#{clean_tag_title}", "#TechStory", "#FutureScience", "#Innovation", "#CaseStudy"]
            else:
                titles = [
                    f"🚀 The Revolutionary Rise of {clean_title} (Inside The Tech Revolution)",
                    f"💡 How {clean_title} Built a Multi-Billion Dollar Empire!",
                    f"⚠️ The Mind-Blowing Future of {clean_title} Explained"
                ]
                desc_hook = f"Inside the engineering genius and paradigm shift of {clean_title}. Discover how this breakthrough is changing our world forever."
                pinned = "💬 Is this the future of innovation or a step too far? Join the discussion below! 👇"
                tags = [f"{clean_title} tech", f"{clean_title} breakdown", "tech revolution", "engineering genius", "business case study"]
                hashtags = [f"#{clean_tag_title}", "#TechStory", "#Innovation", "#Engineering", "#FutureTech"]

        elif genre == "video_essay":
            if lang in ["ur", "hi"]:
                titles = [
                    f"🎭 {clean_title} کے بارے میں سب کیوں غلط تھے؟ (Visual Essay)",
                    f"🧠 اس کہانی کا اصل فلسفہ کیا تھا؟ {clean_title} Deep Dive & Hidden Meaning",
                    f"🔥 سب سے بڑا فریب! {clean_title} کی گہری نفسیاتی سچائی"
                ]
                desc_hook = f"ایک گہرا، بصیرت افروز ویڈیو مضمون: {clean_title}۔ ہم اس کہانی اور کرداروں کے اندر چھپے فلسفے کو بے نقاب کرتے ہیں۔"
                pinned = "💬 کیا آپ کا بھی اس تھیسس سے اتفاق ہے؟ اپنی تنقیدی رائے ضرور لکھیں! 👇"
                tags = [f"{clean_title} video essay", f"{clean_title} hidden meaning", "cinema analysis", "philosophy explained", "character study"]
                hashtags = [f"#{clean_tag_title}", "#VideoEssay", "#CinemaAnalysis", "#Philosophy", "#DeepDive"]
            else:
                titles = [
                    f"🎭 Why Everyone Was Wrong About {clean_title} (Video Essay)",
                    f"🧠 The Hidden Philosophical Genius of {clean_title} Explained",
                    f"🔥 The Illusion That Fooled Everyone in {clean_title}"
                ]
                desc_hook = f"A cultural and cinematic critique breaking down the hidden motifs and psychological thesis of {clean_title}."
                pinned = "💬 Did you catch this subtle symbolism the first time you watched it? Tell us below! 👇"
                tags = [f"{clean_title} video essay", f"{clean_title} analysis", "film essay", "character analysis", "philosophy"]
                hashtags = [f"#{clean_tag_title}", "#VideoEssay", "#FilmAnalysis", "#DeepDive", "#CinemaStudy"]

        else: # movie_recap (Default)
            if lang in ["ur", "hi"]:
                titles = [
                    f"😱 {clean_title} کی یہ کہانی آپ کے ہوش اڑا دے گی! (Full Movie Explained)",
                    f"⚠️ سب سے بڑا دھوکہ! {clean_title} Story Recap & Ending Explained",
                    f"🔥 جب قاتل کا اصل چہرہ سامنے آیا! {clean_title} Full Hindi/Urdu Explanation"
                ]
                desc_hook = f"آج کی اس ویڈیو میں ہم آپ کو بتائیں گے {clean_title} کی سنسنی خیز اور مکمل کہانی۔ آخر تک دیکھیں اور لائک و سبسکرائب کرنا نہ بھولیں!"
                pinned = "💬 آپ کو اس کہانی میں سب سے بڑا موڑ کون سا لگا؟ کمنٹ میں اپنی رائے ضرور بتائیں! 👇"
                tags = [f"{clean_title} explained in urdu", f"{clean_title} hindi recap", "movie explainer", "ending explained", "viral story recap", "hindi movie summary"]
                hashtags = [f"#{clean_tag_title}", "#MovieRecap", "#UrduExplainer", "#HindiMovieRecap", "#TrendingRecap"]
            elif lang == "es":
                titles = [
                    f"😱 ¡El SECRETO de {clean_title} que la policía ocultó! (Resumen Completo)",
                    f"⚠️ ¡Nadie vio venir este final! {clean_title} Explicada en Minutos",
                    f"🔥 ¡No confíes en nadie! La impactante historia de {clean_title}"
                ]
                desc_hook = f"En este video te explicamos la fascinante y aterradora historia de {clean_title}. ¡Mira hasta el final y suscríbete para más resúmenes de películas!"
                pinned = "💬 ¿Qué te pareció el final de esta película? ¡Déjamelo saber en los comentarios! 👇"
                tags = [f"{clean_title} explicacion", f"{clean_title} resumen", "resumen de peliculas", "final explicado", "peliculas en minutos"]
                hashtags = [f"#{clean_tag_title}", "#ResumenDePeliculas", "#PeliculasEnMinutos", "#CineRecap"]
            elif lang == "id":
                titles = [
                    f"😱 RAHASIA KELAM di Balik {clean_title} yang Bikin Merinding! (Alur Cerita)",
                    f"⚠️ Jangan Nonton Sendirian! Alur Cerita Lengkap {clean_title}",
                    f"🔥 Akhir Paling Tak Terduga! {clean_title} Rangkuman Film"
                ]
                desc_hook = f"Berikut adalah alur cerita lengkap dan penjelasan ending dari film {clean_title}. Tonton sampai habis dan jangan lupa like & subscribe!"
                pinned = "💬 Menurut kalian, siapa karakter paling licik di film ini? Tulis di kolom komentar ya! 👇"
                tags = [f"alur cerita {clean_title}", f"rekap film {clean_title}", "alur cerita film", "rangkuman film", "movie recap indonesia"]
                hashtags = [f"#{clean_tag_title}", "#AlurCeritaFilm", "#RekapFilm", "#NontonFilm"]
            elif lang == "ar":
                titles = [
                    f"😱 الصدمة الكبرى في قصة {clean_title}! (ملخص الفيلم كامل)",
                    f"⚠️ النهاية التي صدمت الملايين! فيلم {clean_title} ملخص كامل",
                    f"🔥 حقيقة غير متوقعة تقلب الموازين في {clean_title}!"
                ]
                desc_hook = f"نقدم لكم اليوم القصة الكاملة والمثيرة لفيلم {clean_title} مع شرح النهاية الصادمة. لا تنسوا الإعجاب والاشتراك بالقناة!"
                pinned = "💬 ما هو أكثر مشهد صدمك في هذا الفيلم؟ شاركنا رأيك في التعليقات! 👇"
                tags = [f"ملخص فيلم {clean_title}", f"شرح فيلم {clean_title}", "ملخص افلام", "نهاية فيلم", "قصة فيلم"]
                hashtags = [f"#{clean_tag_title}", "#ملخص_افلام", "#سينما", "#افلام_رعب"]
            else:
                titles = [
                    f"😱 Nobody Expected the Twisted Ending of {clean_title}! (Full Movie Recap)",
                    f"⚠️ THE WORST MISTAKE! {clean_title} Story & Ending Explained",
                    f"🔥 He Thought He Was Safe Until... {clean_title} Movie Recap"
                ]
                desc_hook = f"In this video, we break down the shocking story and unexpected twists of {clean_title}. Watch until the end and subscribe for more viral movie recaps!"
                pinned = "💬 What was your favorite moment from this story? Let us know in the comments below! 👇"
                tags = [f"{clean_title} movie recap", f"{clean_title} explained", "movie recap", "ending explained", "story recap", "films in minutes"]
                hashtags = [f"#{clean_tag_title}", "#MovieRecap", "#StoryRecap", "#EndingExplained", "#TrendingMovies"]

        disclaimer = (
            "\n\n---\n⚖️ COPYRIGHT & FAIR USE DISCLAIMER:\n"
            "This video is for educational, critical commentary, and storytelling purposes. "
            "Under Section 107 of the Copyright Act 1976, allowance is made for 'fair use' for purposes such as criticism, commentary, news reporting, teaching, and research."
        )

        full_description = f"{desc_hook}\n\n🎬 Topic/Title: {clean_title}\n\n{' '.join(hashtags)}{disclaimer}"

        return {
            "movie_title": clean_title,
            "genre": genre,
            "titles": titles,
            "description": full_description,
            "tags": tags,
            "hashtags": hashtags,
            "pinned_comment": pinned
        }
