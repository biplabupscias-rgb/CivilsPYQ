# quiz/admin_resource.py
from import_export import resources, fields
from .models import Question, Option

class QuestionResource(resources.ModelResource):
    # --- 1. OPTION A ---
    opt_a_text = fields.Field(attribute='opt_a_text', column_name='opt_a_text')
    opt_a_expl = fields.Field(attribute='opt_a_expl', column_name='opt_a_expl')
    opt_a_img  = fields.Field(attribute='opt_a_img', column_name='opt_a_img')
    opt_a_vid  = fields.Field(attribute='opt_a_vid', column_name='opt_a_vid')
    opt_a_mnem = fields.Field(attribute='opt_a_mnem', column_name='opt_a_mnem')

    # --- 2. OPTION B ---
    opt_b_text = fields.Field(attribute='opt_b_text', column_name='opt_b_text')
    opt_b_expl = fields.Field(attribute='opt_b_expl', column_name='opt_b_expl')
    opt_b_img  = fields.Field(attribute='opt_b_img', column_name='opt_b_img')
    opt_b_vid  = fields.Field(attribute='opt_b_vid', column_name='opt_b_vid')
    opt_b_mnem = fields.Field(attribute='opt_b_mnem', column_name='opt_b_mnem')

    # --- 3. OPTION C ---
    opt_c_text = fields.Field(attribute='opt_c_text', column_name='opt_c_text')
    opt_c_expl = fields.Field(attribute='opt_c_expl', column_name='opt_c_expl')
    opt_c_img  = fields.Field(attribute='opt_c_img', column_name='opt_c_img')
    opt_c_vid  = fields.Field(attribute='opt_c_vid', column_name='opt_c_vid')
    opt_c_mnem = fields.Field(attribute='opt_c_mnem', column_name='opt_c_mnem')

    # --- 4. OPTION D ---
    opt_d_text = fields.Field(attribute='opt_d_text', column_name='opt_d_text')
    opt_d_expl = fields.Field(attribute='opt_d_expl', column_name='opt_d_expl')
    opt_d_img  = fields.Field(attribute='opt_d_img', column_name='opt_d_img')
    opt_d_vid  = fields.Field(attribute='opt_d_vid', column_name='opt_d_vid')
    opt_d_mnem = fields.Field(attribute='opt_d_mnem', column_name='opt_d_mnem')

    correct_opt_label = fields.Field(attribute='correct_option', column_name='correct_option')
    question_img = fields.Field(attribute='question_image_url', column_name='question_image_url')

    class Meta:
        model = Question
        # Whitelist all fields so Django doesn't complain
        fields = (
            'id', 'text', 'exam_name', 'year', 'subject', 'tags',
            'opt_a_text', 'opt_a_expl', 'opt_a_img', 'opt_a_vid', 'opt_a_mnem',
            'opt_b_text', 'opt_b_expl', 'opt_b_img', 'opt_b_vid', 'opt_b_mnem',
            'opt_c_text', 'opt_c_expl', 'opt_c_img', 'opt_c_vid', 'opt_c_mnem',
            'opt_d_text', 'opt_d_expl', 'opt_d_img', 'opt_d_vid', 'opt_d_mnem',
            'correct_opt_label', 'question_img'
        )
        import_id_fields = ('text',)

    # --- NEW: AUTO-FILL DEFAULTS ---
    def before_import_row(self, row, **kwargs):
        # If year is missing in Excel, force it to 2025
        if 'year' not in row or not row['year']:
            row['year'] = 2025
        
        # If exam_name is missing, force it to UPSC CSE
        if 'exam_name' not in row or not row['exam_name']:
            row['exam_name'] = 'UPSC CSE'

    def after_save_instance(self, instance, using_transactions, dry_run, **kwargs):
        if dry_run: return 

        row = instance.dataset_row
        correct_lbl = str(row.get('correct_option', '')).strip().upper()

        # Map options - We use .get() so if column is missing, it just stays None (Safe)
        options_map = [
            ('A', 'opt_a_text', 'opt_a_expl', 'opt_a_img', 'opt_a_vid', 'opt_a_mnem'),
            ('B', 'opt_b_text', 'opt_b_expl', 'opt_b_img', 'opt_b_vid', 'opt_b_mnem'),
            ('C', 'opt_c_text', 'opt_c_expl', 'opt_c_img', 'opt_c_vid', 'opt_c_mnem'),
            ('D', 'opt_d_text', 'opt_d_expl', 'opt_d_img', 'opt_d_vid', 'opt_d_mnem'),
        ]

        instance.options.all().delete()

        for label, txt_key, expl_key, img_key, vid_key, mnem_key in options_map:
            text_val = row.get(txt_key)
            
            if text_val is not None:
                text_str = str(text_val).strip()
                if text_str: 
                    Option.objects.create(
                        question=instance,
                        option_label=label,
                        text_content=text_str,
                        is_correct=(label == correct_lbl),
                        # If these columns are deleted in Excel, .get() returns None, which is fine
                        explanation_text=row.get(expl_key),
                        image_url=row.get(img_key),
                        video_url=row.get(vid_key),
                        mnemonic_text=row.get(mnem_key)
                    )
