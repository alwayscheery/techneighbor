from io import BytesIO
from PIL import Image, ImageOps, UnidentifiedImageError
from django import forms
from django.utils import timezone
from .models import PhotoAlbum, CommunityPost, PhotoReport

MAX_UPLOAD = 8 * 1024 * 1024


class PhotoUploadForm(forms.Form):
    album = forms.ModelChoiceField(queryset=PhotoAlbum.objects.all(), empty_label='Choose an album')
    image = forms.FileField(label='Choose a photo', widget=forms.ClearableFileInput(attrs={'accept': '.jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp'}))
    title = forms.CharField(max_length=90, label='Give your photo a title')
    caption = forms.CharField(max_length=500, required=False, label='A little story (optional)', widget=forms.Textarea(attrs={'rows': 3}))
    image_description = forms.CharField(max_length=250, label='Describe what is in the photo', help_text='This description helps people who use a screen reader.', widget=forms.Textarea(attrs={'rows': 2}))
    uploader_name = forms.CharField(max_length=60, label='Your first name or nickname', help_text='Shown with the photo after approval.')
    permission = forms.BooleanField(label='I have permission to share this photo, and anyone pictured has agreed.')

    def clean_image(self):
        upload = self.cleaned_data['image']
        if upload.size > MAX_UPLOAD:
            raise forms.ValidationError('Please choose a photo smaller than 8 MB.')
        try:
            image = Image.open(upload)
            # Phone JPEGs can contain auxiliary images (MPO / multi-picture JPEG).
            # Normalize only the primary photograph, just as for other uploads.
            if image.format not in ('JPEG', 'MPO', 'PNG', 'WEBP'):
                raise forms.ValidationError(
                    f'This file contains {image.format or "an unsupported image format"} data, even if its name ends in .jpg. '
                    'Export or save a copy as JPEG, PNG, or WebP, then choose that copy.')
            image.seek(0)
            if image.width * image.height > 24_000_000:
                raise forms.ValidationError('This photo is too large to process. Choose a smaller copy, up to 24 megapixels.')
            image.load()
            image = ImageOps.exif_transpose(image)
            if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
                rgba = image.convert('RGBA')
                converted = Image.new('RGB', rgba.size, (250, 248, 242))
                converted.paste(rgba, mask=rgba.getchannel('A'))
                image = converted
            else:
                image = image.convert('RGB')
            image.thumbnail((2000, 2000))
            # Re-encoding without metadata removes embedded location and EXIF data.
            output = BytesIO()
            image.save(output, format='JPEG', quality=82, optimize=True)
            data = output.getvalue()
            if len(data) > 2 * 1024 * 1024:
                raise forms.ValidationError('Please choose a simpler or smaller photo, then try again.')
            return {'data': data, 'width': image.width, 'height': image.height}
        except forms.ValidationError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise forms.ValidationError('That file could not be read as a photo. Please choose a JPG, PNG, or WebP image.') from exc


class CommunityPostForm(forms.ModelForm):
    class Meta:
        model = CommunityPost
        fields = ['kind', 'title', 'body', 'starts_at', 'location', 'capacity']
        labels = {'kind': 'Type of post', 'body': 'Details', 'starts_at': 'Activity date and time (Pacific)', 'capacity': 'Places available'}
        widgets = {'body': forms.Textarea(attrs={'rows': 4}), 'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')}

    def clean(self):
        data = super().clean()
        if data.get('kind') == 'event':
            if not data.get('starts_at') or data['starts_at'] <= timezone.now():
                self.add_error('starts_at', 'Choose a future date and time for the activity.')
            if not data.get('capacity') or data['capacity'] > 100:
                self.add_error('capacity', 'Choose between 1 and 100 places.')
        else:
            data['starts_at'] = None
        return data


class AttendanceForm(forms.Form):
    display_name = forms.CharField(max_length=60, label='Your first name or nickname')


class PhotoReportForm(forms.ModelForm):
    class Meta:
        model = PhotoReport
        fields = ['reason']
