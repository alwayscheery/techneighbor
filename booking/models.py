import uuid
from django.core.validators import RegexValidator
from django.db import models

SUPPORT_CATEGORIES = {
    'companionship': {
        'label': 'Companionship', 'icon': 'heart', 'color': 'green',
        'description': 'A friendly chat, a gentle walk, or a game together.',
        'topics': [('chat', 'A friendly chat'), ('walk', 'A gentle walk together'), ('games', 'A board game together')],
        'preparation': 'Just bring yourself',
        'preparation_note': 'For a walk, meet your helper at the center’s welcome desk. Choose a pace and route you are comfortable with.',
        'location': 'Community lounge · Meet at the welcome desk',
        'session_note': 'Time to talk, enjoy a shared activity, and get to know a neighbor.',
    },
    'everyday': {
        'label': 'Everyday help', 'icon': 'hands', 'color': 'peach',
        'description': 'Plan errands, organize a small task, or read an everyday letter together.',
        'topics': [('errands', 'Plan everyday errands'), ('organize', 'Organize a small task'), ('letters', 'Read an everyday letter together')],
        'preparation': 'Bring the task you have in mind',
        'preparation_note': 'Bring a list or a non-sensitive letter. We’ll work through it together at the center.',
        'location': 'Community help desk · Meet at the welcome desk',
        'session_note': 'Practical support with a small everyday task, at the center.',
    },
    'technology': {
        'label': 'Technology help', 'icon': 'phone', 'color': 'lavender',
        'description': 'Get comfortable with video calls, your phone, and sharing photos.',
        'topics': [('video', 'Video calls'), ('phone', 'Phone basics'), ('photos', 'Photos & sharing')],
        'preparation': 'Bring your own device',
        'preparation_note': 'Your phone or tablet, charged and ready. Your helper will guide you while you stay in control.',
        'location': 'Learning room · Meet at the welcome desk',
        'session_note': 'One topic. Plenty of time to learn and practice at your pace.',
    },
}
TOPICS = [topic for category in SUPPORT_CATEGORIES.values() for topic in category['topics']]
TOPIC_CATEGORY = {topic: key for key, category in SUPPORT_CATEGORIES.items() for topic, _ in category['topics']}

class SessionSlot(models.Model):
    starts_at = models.DateTimeField(unique=True)
    venue = models.CharField(max_length=160, default='Maple Community Center')
    duration_minutes = models.PositiveIntegerField(default=30)

    class Meta:
        ordering = ['starts_at']

    def __str__(self):
        from django.utils import timezone
        return f'{timezone.localtime(self.starts_at):%a, %b %d at %I:%M %p} — {self.venue}'

class Booking(models.Model):
    class Status(models.TextChoices):
        BOOKED = 'booked', 'Booked'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    slot = models.ForeignKey(SessionSlot, on_delete=models.PROTECT, related_name='bookings')
    topic = models.CharField(max_length=20, choices=TOPICS)
    name = models.CharField(max_length=80)
    contact = models.CharField(max_length=120, blank=True)
    booking_for = models.CharField(max_length=12, choices=[('self', 'Myself'), ('someone', 'Someone else')], default='self')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.BOOKED)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    is_sample = models.BooleanField(default=False)

    class Meta:
        ordering = ['slot__starts_at']
        constraints = [models.UniqueConstraint(
            fields=['slot'], condition=models.Q(status__in=['booked', 'completed']),
            name='one_active_booking_per_slot',
        )]

    def __str__(self):
        return f'{self.name} — {self.get_topic_display()}'

    @property
    def support_category(self):
        return TOPIC_CATEGORY[self.topic]

    @property
    def support_details(self):
        return SUPPORT_CATEGORIES[self.support_category]


class ServiceCredential(models.Model):
    """Private link to a booking; public proof contains only blockchain identifiers."""
    booking = models.OneToOneField(Booking, on_delete=models.PROTECT, related_name='credential')
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    volunteer_alias = models.CharField(max_length=80)
    volunteer_wallet = models.CharField(max_length=42, validators=[RegexValidator(r'^0x[0-9a-fA-F]{40}$', 'Enter an EVM wallet address.')])
    issuer_wallet = models.CharField(max_length=42)
    contract_address = models.CharField(max_length=42)
    chain_id = models.PositiveIntegerField(default=5042002)
    status = models.CharField(max_length=20, default='draft', choices=[
        ('draft', 'Not submitted'), ('pending', 'Issuance pending'), ('issued', 'Issued'),
        ('revoke_pending', 'Revocation pending'), ('revoked', 'Revoked'), ('failed', 'Transaction failed'),
    ])
    issue_tx = models.CharField(max_length=66, blank=True)
    revoke_tx = models.CharField(max_length=66, blank=True)
    issue_raw = models.TextField(blank=True, editable=False)
    revoke_raw = models.TextField(blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def chain_uid(self):
        return '0x' + self.public_id.hex.rjust(64, '0')

    def __str__(self):
        return f'Service credential {self.public_id}'


class VolunteerReward(models.Model):
    """Only random public_id, recipient, amount and transaction are published."""
    booking = models.OneToOneField(Booking, on_delete=models.PROTECT, related_name='reward', null=True, blank=True)
    support_task = models.OneToOneField('SupportTask', on_delete=models.PROTECT, related_name='reward', null=True, blank=True)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    volunteer_wallet = models.CharField(max_length=42)
    approved_by = models.ForeignKey('auth.User', on_delete=models.PROTECT, null=True, blank=True)
    approved_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=12, default='approved', choices=[
        ('requested', 'Awaiting coordinator approval'), ('approved', 'Approved, not paid'), ('pending', 'Awaiting confirmation'),
        ('paid', 'Paid on Arc Testnet'), ('failed', 'Transaction failed'),
    ])
    transaction_hash = models.CharField(max_length=66, blank=True, unique=True, null=True)
    signed_transaction = models.TextField(blank=True, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=(
            models.Q(booking__isnull=False, support_task__isnull=True) |
            models.Q(booking__isnull=True, support_task__isnull=False)
        ), name='reward_has_exactly_one_source')]

    @property
    def chain_uid(self):
        return '0x' + self.public_id.hex.rjust(64, '0')


class CommunityPost(models.Model):
    slug = models.SlugField(unique=True, max_length=100)
    kind = models.CharField(max_length=12, choices=[('event', 'Activity'), ('notice', 'Announcement')])
    title = models.CharField(max_length=100)
    body = models.TextField(max_length=2500)
    starts_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=160, default='Maple Community Center')
    capacity = models.PositiveSmallIntegerField(default=12)
    going_count = models.PositiveIntegerField(default=0, editable=False)
    published = models.BooleanField(default=True)
    is_sample = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def places_left(self):
        return max(0, self.capacity - self.going_count)

    def __str__(self):
        return self.title


class CommunityAttendance(models.Model):
    event = models.ForeignKey(CommunityPost, on_delete=models.CASCADE, related_name='attendees')
    owner_token = models.CharField(max_length=64, editable=False)
    display_name = models.CharField(max_length=60)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['event', 'owner_token'], name='one_event_place_per_device')]


class PhotoAlbum(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=80)
    description = models.CharField(max_length=300)
    color = models.CharField(max_length=12, default='lavender', choices=[('lavender', 'Lavender'), ('green', 'Green'), ('peach', 'Peach')])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class CommunityPhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    album = models.ForeignKey(PhotoAlbum, on_delete=models.PROTECT, related_name='photos')
    title = models.CharField(max_length=90)
    caption = models.CharField(max_length=500, blank=True)
    image_description = models.CharField(max_length=250)
    uploader_name = models.CharField(max_length=60)
    owner_token = models.CharField(max_length=64, editable=False)
    image_data = models.BinaryField(editable=False)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    status = models.CharField(max_length=10, default='pending', choices=[('pending', 'Awaiting review'), ('approved', 'Shared'), ('hidden', 'Removed')])
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class PhotoReport(models.Model):
    photo = models.ForeignKey(CommunityPhoto, on_delete=models.CASCADE, related_name='reports')
    owner_token = models.CharField(max_length=64, editable=False)
    reason = models.CharField(max_length=20, choices=[('privacy', 'Privacy or permission'), ('content', 'Inappropriate photo'), ('other', 'Something else')])
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['photo', 'owner_token'], name='one_photo_report_per_device')]


class NeighborArea(models.Model):
    state = models.CharField(max_length=2, blank=True, db_index=True)
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class NeighborProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_token = models.CharField(max_length=64, unique=True, editable=False)
    area = models.ForeignKey(NeighborArea, on_delete=models.PROTECT, related_name='neighbors')
    nickname = models.CharField(max_length=40)
    interest = models.CharField(max_length=20, choices=[('company', 'Coffee & conversation'), ('walking', 'Gentle walks'), ('technology', 'Learning technology'), ('photos', 'Photos & stories')])
    about = models.CharField(max_length=240)
    status = models.CharField(max_length=12, default='pending', choices=[('pending', 'Awaiting review'), ('approved', 'Listed'), ('hidden', 'Not listed')])
    is_sample = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class NeighborIntroduction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(NeighborProfile, on_delete=models.CASCADE, related_name='introductions_sent')
    neighbor = models.ForeignKey(NeighborProfile, on_delete=models.CASCADE, related_name='introductions_received')
    contact = models.CharField(max_length=120)
    note = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=12, default='pending', choices=[('pending', 'Needs review'), ('arranged', 'Handled'), ('closed', 'Closed')])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['requester', 'neighbor'], condition=models.Q(status='pending'), name='one_pending_neighbor_introduction')]


class HostedGuideAudio(models.Model):
    """Only pre-generated fixed guide clips; never API keys or resident speech."""
    cache_key = models.CharField(max_length=64, primary_key=True)
    prompt = models.CharField(max_length=40)
    audio_data = models.BinaryField(editable=False)


class SupportCircle(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey('auth.User', on_delete=models.PROTECT, related_name='owned_support_circles')
    name = models.CharField(max_length=80)
    timezone = models.CharField(max_length=64, default='America/Chicago')
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class SupportMember(models.Model):
    circle = models.ForeignKey(SupportCircle, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey('auth.User', on_delete=models.PROTECT, related_name='support_memberships')
    role = models.CharField(max_length=12, choices=[('owner', 'Organizer'), ('family', 'Family member'), ('neighbor', 'Approved neighbor')])
    neighbor_profile = models.ForeignKey(NeighborProfile, on_delete=models.PROTECT, null=True, blank=True)
    active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['circle', 'user'], name='one_support_membership')]


class SupportNeighborIdentity(models.Model):
    user = models.OneToOneField('auth.User', on_delete=models.PROTECT)
    profile = models.OneToOneField(NeighborProfile, on_delete=models.PROTECT)


class SupportInvite(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    circle = models.ForeignKey(SupportCircle, on_delete=models.CASCADE, related_name='invites')
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    role = models.CharField(max_length=12, choices=[('family', 'Family member'), ('neighbor', 'Approved neighbor')])
    expires_at = models.DateTimeField()
    used_by = models.ForeignKey('auth.User', on_delete=models.PROTECT, null=True, blank=True)
    revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class SupportTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    circle = models.ForeignKey(SupportCircle, on_delete=models.CASCADE, related_name='tasks')
    created_by = models.ForeignKey('auth.User', on_delete=models.PROTECT, related_name='support_tasks_created')
    title = models.CharField(max_length=100)
    details = models.TextField(max_length=1000, blank=True)
    category = models.CharField(max_length=16, choices=[('company', 'Company & visits'), ('technology', 'Technology help'), ('errands', 'Everyday errands'), ('transport', 'A ride or outing'), ('other', 'Other support')])
    due_at = models.DateTimeField(null=True, blank=True)
    assignee = models.ForeignKey('auth.User', on_delete=models.PROTECT, null=True, blank=True, related_name='support_tasks_claimed')
    status = models.CharField(max_length=12, default='open', choices=[('open', 'Needs a volunteer'), ('claimed', 'Volunteer assigned'), ('review', 'Awaiting confirmation'), ('done', 'Completed'), ('cancelled', 'Cancelled')])
    created_at = models.DateTimeField(auto_now_add=True)


class SupportActivity(models.Model):
    circle = models.ForeignKey(SupportCircle, on_delete=models.CASCADE, related_name='activity')
    actor = models.ForeignKey('auth.User', on_delete=models.PROTECT)
    action = models.CharField(max_length=60)
    task = models.ForeignKey(SupportTask, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
