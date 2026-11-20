from django import forms
from .models import CARE_KINDS

ACCESS = [('none', 'Not shared'), ('view', 'View only'), ('help', 'View and suggest updates')]


class CareAccessForm(forms.Form):
    appointments = forms.ChoiceField(choices=ACCESS, required=False, initial='none', label='Appointments')
    medications = forms.ChoiceField(choices=ACCESS, required=False, initial='none', label='Medication coordination')
    contacts = forms.ChoiceField(choices=ACCESS, required=False, initial='none', label='Care contacts')
    benefits = forms.ChoiceField(choices=ACCESS, required=False, initial='none', label='Benefit renewal reminders')

    def permissions(self):
        return {kind: self.cleaned_data.get(kind) or 'none' for kind, _ in CARE_KINDS}


class RecordForm(forms.Form):
    version = forms.IntegerField(required=False, min_value=0, widget=forms.HiddenInput)


class AppointmentForm(RecordForm):
    title = forms.CharField(max_length=100, label='Appointment name')
    when = forms.DateTimeField(label='Date and time', widget=forms.DateTimeInput(attrs={'type':'datetime-local'}, format='%Y-%m-%dT%H:%M'), input_formats=['%Y-%m-%dT%H:%M'])
    duration = forms.IntegerField(initial=30, min_value=5, max_value=240, label='Duration in minutes')
    location = forms.CharField(max_length=160, required=False, label='Clinic or meeting place')
    notes = forms.CharField(max_length=1000, required=False, widget=forms.Textarea(attrs={'rows':3}))
    status = forms.ChoiceField(choices=[('scheduled','Scheduled'),('attended','Attended'),('cancelled','Cancelled')], initial='scheduled')


class MedicationForm(RecordForm):
    name = forms.CharField(max_length=100, label='Medication name, as prescribed')
    instructions = forms.CharField(max_length=1000, required=False, label='Existing prescriber instructions', widget=forms.Textarea(attrs={'rows':3}), help_text='Copy existing instructions only. This app does not prescribe medication or recommend changes.')
    schedule = forms.CharField(max_length=200, required=False, label='Reminder schedule shown in this planner', help_text='For example, the times already provided by the prescriber. No automatic email or phone alerts are sent.')
    pharmacy = forms.CharField(max_length=160, required=False)
    refill_at = forms.DateTimeField(required=False, label='Refill or pickup reminder', widget=forms.DateTimeInput(attrs={'type':'datetime-local'}, format='%Y-%m-%dT%H:%M'), input_formats=['%Y-%m-%dT%H:%M'])
    status = forms.ChoiceField(choices=[('listed','On the list'),('refill_due','Refill due'),('requested','Refill requested'),('ready','Ready for pickup'),('picked_up','Picked up')], initial='listed')


class ContactForm(RecordForm):
    name = forms.CharField(max_length=100, label='Contact name')
    role = forms.ChoiceField(choices=[('family','Family'),('neighbor','Neighbor'),('provider','Care provider'),('pharmacy','Pharmacy'),('other','Other')])
    phone = forms.CharField(max_length=40, required=False, label='Phone number')
    notes = forms.CharField(max_length=1000, required=False, widget=forms.Textarea(attrs={'rows':3}))


class BenefitForm(RecordForm):
    name = forms.CharField(max_length=100, label='Benefit or paperwork reminder')
    renewal_at = forms.DateTimeField(required=False, label='Renewal reminder date and time', widget=forms.DateTimeInput(attrs={'type':'datetime-local'}, format='%Y-%m-%dT%H:%M'), input_formats=['%Y-%m-%dT%H:%M'])
    notes = forms.CharField(max_length=1000, required=False, label='Renewal steps', help_text='Do not include insurance IDs, government identifiers, or financial account numbers.', widget=forms.Textarea(attrs={'rows':3}))
    status = forms.ChoiceField(choices=[('todo','To do'),('in_progress','In progress'),('done','Done')], initial='todo')


FORMS = {'appointments':AppointmentForm, 'medications':MedicationForm, 'contacts':ContactForm, 'benefits':BenefitForm}
DATE_FIELDS = {'appointments':'when','medications':'refill_at','benefits':'renewal_at'}
