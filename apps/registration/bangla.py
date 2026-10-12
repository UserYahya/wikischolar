"""
Bangla next to the English on the public registration form.

The form is English-first (answers must be typed in English); every label, hint, button and message
also shows a smaller Bangla line. Labels written in the template carry their Bangla there. Messages
that come from Python (form errors, API errors) or are built in static/js/register.js are looked up
here by their exact English text; the page passes this dict to the script as JSON. {email}, {time},
{s} and {name} are filled in by the script.

A test checks that every server-side message has a translation, so new messages can't slip through
untranslated.
"""
from apps.core.utils import ENGLISH_ONLY_MESSAGE

from .choices import CLASS_CHOICES, Gender, GuardianRelation, HeardFrom

MESSAGES = {
    # Field checks (forms.py, validators.py, register.js)
    "This field is required.": "এই ঘরটি পূরণ করা আবশ্যক।",
    "Please choose one.": "যেকোনো একটি বেছে নিন।",
    "Select a valid choice. That choice is not one of the available choices.":
        "তালিকা থেকে একটি সঠিক বিকল্প বেছে নিন।",
    "Enter a whole number.": "শুধু সংখ্যা লিখুন।",
    ENGLISH_ONLY_MESSAGE: "অনুগ্রহ করে ইংরেজিতে লিখুন (শুধু A-Z অক্ষর ও 0-9 সংখ্যা)।",
    "Enter a valid Bangladeshi mobile number (for example 01712345678).":
        "সঠিক বাংলাদেশি মোবাইল নম্বর লিখুন (যেমন 01712345678)।",
    "Enter a valid email address.": "সঠিক ইমেইল ঠিকানা লিখুন।",
    "Write the email address in English letters.": "ইমেইল ঠিকানা ইংরেজি অক্ষরে লিখুন।",
    "Fill in either the class roll or the student ID.": "রোল নম্বর অথবা শিক্ষার্থী আইডি, অন্তত একটি লিখুন।",
    "Write the class roll in numbers only (for example 12).": "রোল নম্বর শুধু সংখ্যায় লিখুন (যেমন 12)।",
    "Write the student's relation to the guardian.": "অভিভাবকের সাথে শিক্ষার্থীর সম্পর্ক লিখুন।",
    "Choose a thana in the selected district.": "বেছে নেওয়া জেলার মধ্যে একটি থানা বেছে নিন।",
    "Choose how you heard about WikiScholar.": "উইকিস্কলারের কথা কোথা থেকে জেনেছেন, তা বেছে নিন।",
    "Tick the guardian declaration: the form must be filled in by the student's guardian.":
        "অভিভাবকের ঘোষণায় টিক দিন: ফর্মটি শিক্ষার্থীর অভিভাবককেই পূরণ করতে হবে।",
    "Agree to the Youth Safety Policy to complete registration.":
        "নিবন্ধন সম্পন্ন করতে যুব সুরক্ষা নীতিতে সম্মতি দিন।",
    "Verify your email address first.": "আগে ইমেইল ঠিকানা যাচাই করুন।",
    "Verify your email address to continue.": "এগিয়ে যেতে ইমেইল ঠিকানা যাচাই করুন।",
    # Server answers (views.py MESSAGES, services.py)
    "Too many attempts. Please wait a while and try again.": "অনেকবার চেষ্টা করা হয়েছে। কিছুক্ষণ পর আবার চেষ্টা করুন।",
    "That code doesn't match. Check it and try again.": "কোডটি মেলেনি। দেখে নিয়ে আবার চেষ্টা করুন।",
    "This code has expired. Send a new one.": "কোডটির মেয়াদ শেষ হয়ে গেছে। নতুন কোড পাঠান।",
    "Too many wrong codes. Send a new one.": "অনেকবার ভুল কোড দেওয়া হয়েছে। নতুন কোড পাঠান।",
    "Verification session not found. Send a new code.": "যাচাইয়ের তথ্য পাওয়া যায়নি। নতুন কোড পাঠান।",
    "Your email isn't verified, or the verification expired. Please verify again.":
        "আপনার ইমেইল যাচাই হয়নি, অথবা যাচাইয়ের মেয়াদ শেষ হয়ে গেছে। আবার যাচাই করুন।",
    "We couldn't send the code. Check the email address and try again.":
        "কোড পাঠানো যায়নি। ইমেইল ঠিকানাটি দেখে নিয়ে আবার চেষ্টা করুন।",
    "The security check didn't pass or has expired. Please do it again.":
        "নিরাপত্তা যাচাই সফল হয়নি বা মেয়াদ শেষ হয়ে গেছে। আবার করুন।",
    "Complete the security check first.": "আগে নিরাপত্তা যাচাইটি সম্পন্ন করুন।",
    "This email address is already registered for another student. Please use a different email address.":
        "এই ইমেইল ঠিকানা দিয়ে অন্য একজন শিক্ষার্থী আগেই নিবন্ধন করেছে। অন্য একটি ইমেইল ঠিকানা ব্যবহার করুন।",
    # Messages built in register.js
    "Couldn't reach the server. Check your internet connection and try again.":
        "সার্ভারের সাথে যোগাযোগ করা যায়নি। ইন্টারনেট সংযোগ দেখে আবার চেষ্টা করুন।",
    "School selected from the list.": "তালিকা থেকে বিদ্যালয় বেছে নেওয়া হয়েছে।",
    "This will be added as a new school; our team will verify it later.":
        "এটি নতুন বিদ্যালয় হিসেবে যোগ হবে; আমাদের দল পরে যাচাই করবে।",
    "Enter the 6-digit code.": "৬ অঙ্কের কোডটি লিখুন।",
    "Did you mean {email}?": "আপনি কি {email} লিখতে চেয়েছিলেন?",
    "Use {email}": "{email} ব্যবহার করুন",
    "We sent a 6-digit code by email to {email}. Can't find it? Check your Spam or Junk folder.":
        "{email} ঠিকানায় ৬ অঙ্কের একটি কোড পাঠানো হয়েছে। খুঁজে না পেলে Spam বা Junk ফোল্ডার দেখুন।",
    "Send a new code": "নতুন কোড পাঠান",
    "Send a new code ({s}s)": "নতুন কোড পাঠান ({s} সেকেন্ড পর)",
    "Code expires in {time}": "কোডটির মেয়াদ আছে আর {time} মিনিট",
    "Choose": "বেছে নিন",
    "Choose a district first": "আগে জেলা বেছে নিন",
    "Choose the thana first": "আগে থানা বেছে নিন",
    "Type in English": "ইংরেজিতে লিখুন",
    "Loading…": "লোড হচ্ছে…",
    "Shown after you choose a district": "জেলা বেছে নিলে দেখা যাবে",
    "No region assigned": "কোনো অঞ্চল নির্ধারণ করা নেই",
    "being verified": "যাচাই চলছে",
    "Not in the list? Add it as new: “{name}”": "তালিকায় নেই? নতুন হিসেবে যোগ করুন: “{name}”",
    "Type at least 3 letters to see suggestions.": "পরামর্শ দেখতে অন্তত ৩টি অক্ষর লিখুন।",
    "Go back to this step": "এই ধাপে ফিরে যান",
    # Summary after registering
    "Filled in by": "যিনি পূরণ করেছেন", "Name": "নাম", "Gender": "লিঙ্গ", "Guardian": "অভিভাবক",
    "District": "জেলা", "Region": "অঞ্চল", "Thana": "থানা", "School": "বিদ্যালয়", "Class": "শ্রেণি",
    "Section": "শাখা", "Class roll": "রোল নম্বর", "Student ID": "শিক্ষার্থী আইডি", "Mobile": "মোবাইল",
    "Heard about WikiScholar from": "উইকিস্কলারের কথা জেনেছেন",
    "Registered on": "নিবন্ধনের তারিখ",
}

# Choice labels, shown next to the English in chips and dropdowns. One dict per choice list: several
# lists use the same value (e.g. "other"), so they can't share a dict.
GENDERS = {Gender.MALE: "ছেলে", Gender.FEMALE: "মেয়ে", Gender.UNDISCLOSED: "বলতে চাই না"}
RELATIONS = {GuardianRelation.FATHER: "বাবা", GuardianRelation.MOTHER: "মা", GuardianRelation.OTHER: "অন্য"}
HEARD_FROM = {
    HeardFrom.SOCIAL_MEDIA: "সামাজিক যোগাযোগমাধ্যম",
    HeardFrom.ONLINE_AD: "গুগল বা ইউটিউবের বিজ্ঞাপন",
    HeardFrom.WIKIPEDIA_NOTICE: "উইকিপিডিয়ার নোটিশ",
    HeardFrom.SCHOOL: "শিক্ষক বা বিদ্যালয়ের ঘোষণা",
    HeardFrom.BANNER: "ব্যানার / লিফলেট ইত্যাদি",
    HeardFrom.VOLUNTEERS: "উইকিপিডিয়ার স্বেচ্ছাসেবকেরা আমাদের বিদ্যালয়ে এসেছিলেন",
    HeardFrom.OTHER: "অন্য কোথাও",
}
CLASSES = {"6": "ষষ্ঠ শ্রেণি", "7": "সপ্তম শ্রেণি", "8": "অষ্টম শ্রেণি", "9": "নবম শ্রেণি", "10": "দশম শ্রেণি"}


def with_bangla(choices, names):
    """[(value, english, bangla), ...] for the template."""
    return [(v, label, names.get(v, "")) for v, label in choices]


def class_choices():
    return [(v, label, CLASSES.get(v, "")) for v, label in CLASS_CHOICES]
