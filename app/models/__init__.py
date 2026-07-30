"""Import every model so Base.metadata.create_all() sees all tables."""
from app.models.admin import ReferralUser, Admin, ActivityLog, Role
from app.models.academic import CampusRollSetting, Course, Department, TransferRequest
from app.models.money_transfer import MoneyTransfer
from app.models.application import (
    Student, Application, ApplicationNote, Payment,
    ApplicationStatus, PaymentStatus, AdmissionStatus, EligibilityStatus,
)
from app.models.installment import Installment, InstallmentStatus, PaymentAllocation
from app.models.expense import Budget, Expense
from app.models.chat import ChatSession, ChatMessage
from app.models.misc import (
    Lead, LeadNote, LeadStatus, LeadSource,
    Notification, NotificationPriority,
)
from app.models.payment_flow import (
    Challan, ChallanStatus, PaymentReceipt, ReceiptStatus,
)
