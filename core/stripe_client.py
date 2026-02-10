import stripe
from core.config import STRIPE_SECRET_KEY

stripe.api_key = STRIPE_SECRET_KEY